"""RAG 问答链模块：LCEL 组合 + 空检索拦截 + 流式支持。

本模块是 RAG 系统的核心编排层，将检索器、Prompt 模板、LLM、
输出解析器和引用提取器组装为端到端的问答管道。

核心设计：
1. **LCEL 生成链**：使用 LCEL 的 | 操作符组合 prompt → llm → StrOutputParser，
   展示 Runnable 协议的链式调用能力（RunnablePassthrough、RunnableLambda、
   RunnableParallel 等组件在 format_docs 和 Chain 组装中体现）。

2. **类方法编排**：检索→拦截→生成→引用提取的完整流程由 RAGChain 类方法控制，
   而非塞入单一 LCEL 管道（决策1），因为需要在多个位置插入拦截逻辑。

3. **流式支持**：stream() 方法逐 token 推送文本，为 Task 5.2 FastAPI SSE 做准备。

4. **空检索拦截**：检索返回空文档时直接返回预设回复，不调用 LLM（节省开销）。

使用示例：
    # 快速启动
    chain = RAGChain.create()
    result = chain.invoke("LangGraph 是什么？")
    print(result.answer)
    print(result.citations)

    # 流式输出
    for chunk in chain.stream("LangGraph 是什么？"):
        print(chunk, end="", flush=True)

    # 自定义配置
    from src.retriever import create_vector_retriever
    from src.generation.prompts import get_prompt, PromptVersion
    from src.core.config import deepseek_llm

    retriever = create_vector_retriever(search_kwargs={"k": 3})
    prompt = get_prompt(PromptVersion.V1)
    chain = RAGChain(retriever=retriever, llm=deepseek_llm, prompt=prompt)
"""

import time
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Iterator, List, Optional

import structlog
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.vectorstores import VectorStoreRetriever

from src.core.config import deepseek_llm
from src.generation.citation_chain import CitationExtractor, ValidatedCitation
from src.generation.exceptions import (
    CitationExtractionError,
    EmptyRetrievalError,
    GenerationError,
    LLMCallError,
)
from src.generation.prompts import PromptVersion, get_prompt
from src.retriever.base_retriever import (
    RetrievalError,
    create_vector_retriever,
)
from src.utils.retry import with_retry

logger = structlog.get_logger(__name__)


# ============================================================
# format_docs 函数
# ============================================================

def format_docs(docs: List[Document]) -> str:
    """将检索到的文档列表格式化为带编号和来源的上下文字符串。

    输出格式与 Prompt V2 的 few-shot 示例严格一致：
        [1] Document content (source: https://example.com/doc1)

        [2] Document content (source: https://example.com/doc2)

    为什么这样格式化：
        1. 编号 [N] 建立文档与引用标记的一一对应关系，LLM 用 [N] 精确引用
        2. source 紧跟内容，LLM 注意力机制对近距离信息遵从度更高
        3. 双换行分隔，让 LLM 清晰区分不同文档片段

    Args:
        docs: 检索器返回的文档列表。
            每个文档需包含 metadata["source"] 字段。
            若缺少 source，使用 "unknown" 占位。

    Returns:
        格式化后的字符串。空列表返回 ""。
    """
    # 第1步：边界处理 — docs 为空 → 返回 ""
    if not docs:
        return ""

    # 第2步：遍历 docs（enumerate 从 1 开始），格式化为 "[N] content (source: URL)"
    formatted_parts: List[str] = []
    for i, doc in enumerate(docs, 1):
        content = doc.page_content
        # 若 page_content 为空字符串，跳过该文档
        # 避免产生 "[N]  (source: URL)" 这种空洞条目
        if not content or not content.strip():
            continue
        source = doc.metadata.get("source", "unknown")
        formatted_parts.append(f"[{i}] {content} (source: {source})")

    # 第3步：用 "\n\n" join 所有格式化后的条目
    result = "\n\n".join(formatted_parts)

    # 第4步：记录日志（格式化文档数量、总字符数）
    logger.debug(
        "文档格式化完成",
        doc_count=len(docs),
        formatted_count=len(formatted_parts),
        total_chars=len(result),
    )

    return result


# ============================================================
# RAGResponse 数据结构
# ============================================================

@dataclass
class RAGResponse:
    """RAG 链的完整响应数据。

    设计意图：
        将回答文本、来源 URL、引用验证结果封装为统一数据结构，
        调用方（CLI/FastAPI/LangGraph 节点）只需处理一个对象。

    为什么用 dataclass 而非 Pydantic BaseModel：
        RAGResponse 是内部数据传输对象，不需要 JSON 序列化/校验。
        dataclass 更轻量，且与 LangChain Document 风格一致。
        若 Task 5.1 FastAPI 需要返回 JSON，可添加一个 to_dict() 方法。

    Attributes:
        answer: LLM 生成的回答文本（含行内引用标记 [1] [2] 等）
        sources: 检索命中的文档 source URL 列表
        citations: 引用验证结果列表（提取失败时为空列表）
        retrieval_count: 检索到的文档数量
    """
    answer: str
    sources: List[str]
    citations: List[ValidatedCitation]
    retrieval_count: int

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（供 FastAPI JSON 序列化使用）。

        为什么需要此方法：
            dataclass 的 dataclasses.asdict() 会递归转换嵌套的 dataclass，
            但 ValidatedCitation 中的 is_valid 等字段需要显式处理。
            自定义 to_dict 确保输出格式稳定可控。

        Returns:
            包含 answer、sources、citations、retrieval_count 的字典
        """
        return {
            "answer": self.answer,
            "sources": self.sources,
            "citations": [
                {"number": c.number, "url": c.url, "is_valid": c.is_valid}
                for c in self.citations
            ],
            "retrieval_count": self.retrieval_count,
        }


# ============================================================
# RAGChain 类
# ============================================================

class RAGChain:
    """生产级 RAG 问答链。

    编排流程：invoke(question) →
        1. retriever.invoke(question) → List[Document]
        2. 空检索检查 → docs 为空则返回预设回复
        3. format_docs(docs) → 上下文字符串
        4. (prompt | llm | StrOutputParser()).invoke({context, question}) → answer
        5. citation_extractor.extract(answer, sources) → List[ValidatedCitation]
        6. 封装为 RAGResponse 返回

    流程中每步都有异常处理和日志记录，详见各方法实现。
    """

    EMPTY_RETRIEVAL_RESPONSE: ClassVar[str] = (
        "抱歉，我在文档库中未找到与您问题相关的内容。"
        "请尝试换个方式提问，或确认您的问题与文档主题相关。"
    )
    """空检索预设回复。

    为什么与 Prompt 中的"幻觉防护"措辞不同：
        Prompt 中的"根据现有文档，我无法回答该问题"是 LLM 在有文档但信息不足时的回答。
        空检索是连文档都没有的场景，需要更明确地告知用户。
        两者的区别类似于"我看了书但没找到答案" vs "我连书都没找到"。
    """

    def __init__(
        self,
        retriever: VectorStoreRetriever,
        llm: BaseChatModel,
        prompt: ChatPromptTemplate,
        citation_extractor: Optional[CitationExtractor] = None,
        empty_retrieval_response: str = EMPTY_RETRIEVAL_RESPONSE,
        raise_on_empty: bool = False,
    ):
        """初始化 RAGChain。

        Args:
            retriever: 向量检索器实例
            llm: Chat 模型实例
            prompt: ChatPromptTemplate 实例
            citation_extractor: 引用提取器，默认创建正则策略的 CitationExtractor()
            empty_retrieval_response: 空检索预设回复文本
            raise_on_empty: 检索为空时是否抛出 EmptyRetrievalError，
                默认 False（返回预设回复）。设 True 时抛异常，供 LangGraph 路由使用。
        """
        # 第1步：保存所有依赖（依赖注入，不在内部创建）
        self._retriever = retriever
        self._llm = llm
        self._prompt = prompt
        self._citation_extractor = citation_extractor or CitationExtractor()
        self._empty_retrieval_response = empty_retrieval_response
        self._raise_on_empty = raise_on_empty

        # 第2步：组装 LCEL 生成链
        # 为什么拆分 prompt|llm 和完整链：
        #   Task 1.7 需要在同步调用中提取 AIMessage 的 token 使用量，
        #   并在 LLM 层面加重试（不含 StrOutputParser），
        #   因此将完整链拆为两部分：
        #   - prompt_llm_chain：返回 AIMessage，用于同步 invoke（带重试 + token 追踪）
        #   - generation_chain：返回 str，用于流式 stream（不需要重试和 token 追踪）
        #
        # LCEL 组合展示了什么知识点：
        #   - | 操作符将多个 Runnable 串联为管道
        #   - ChatPromptTemplate 是 Runnable，接收 dict 输出 ChatPromptValue
        #   - BaseChatModel 是 Runnable，接收 ChatPromptValue 输出 AIMessage
        #   - StrOutputParser 是 Runnable，接收 AIMessage 输出 str
        #   这三步通过 | 串联，每步的输出类型自动匹配下一步的输入类型
        self._generation_chain = self._prompt | self._llm | StrOutputParser()
        self._prompt_llm_chain = self._prompt | self._llm

        # 第3步：创建带重试的 LLM 调用函数
        # 为什么在 __init__ 中创建：self._prompt_llm_chain 在此才可用
        # 为什么用 with_retry 而非装饰器：装饰器在类定义时绑定，
        #   而 prompt_llm_chain.invoke 是实例方法，需要运行时动态包装
        self._retryable_invoke = with_retry(
            self._prompt_llm_chain.invoke,
            max_attempts=3,
            min_wait=4,
            max_wait=10,
        )

        # 第4步：记录初始化日志
        logger.info(
            "RAGChain 初始化完成",
            prompt_variables=prompt.input_variables,
            raise_on_empty=raise_on_empty,
        )

    def invoke(self, question: str) -> RAGResponse:
        """同步调用完整 RAG 管道。

        完整流程：
            检索 → 空检索拦截 → 格式化文档 → LCEL 生成 → 引用提取 → 返回 RAGResponse

        Args:
            question: 用户问题（中文）

        Returns:
            RAGResponse 包含回答、来源、引用验证结果

        Raises:
            LLMCallError: LLM 调用失败时（包装底层 API 异常）
            EmptyRetrievalError: raise_on_empty=True 且检索为空时
        """
        total_start = time.perf_counter()

        # ===== 第1步：检索 =====
        # 为什么这样做：检索是 RAG 的第一步，获取与问题相关的文档片段
        retrieve_start = time.perf_counter()
        try:
            docs = self._retriever.invoke(question)
        except RetrievalError as e:
            # 检索模块的异常包装为 GenerationError 向上传播
            # 为什么不直接传播 RetrievalError：
            #   对上层调用方而言，检索失败也是"生成失败"的一种，
            #   统一用 GenerationError 基类捕获即可。
            raise GenerationError(
                f"检索阶段失败，问题: '{question[:50]}...': {e}"
            ) from e
        retrieval_ms = (time.perf_counter() - retrieve_start) * 1000

        logger.info(
            "检索完成",
            question=question[:50],
            doc_count=len(docs),
            latency_ms=round(retrieval_ms, 1),
        )

        # ===== 第2步：空检索拦截 =====
        # 为什么这样做：检索为空时调用 LLM 没有意义（无上下文的 LLM 会产生幻觉），
        #   直接返回预设回复既节省 API 开销，又保证回答质量
        if not docs:
            logger.warning(
                "检索返回空结果",
                question=question[:50],
                raise_on_empty=self._raise_on_empty,
            )
            if self._raise_on_empty:
                raise EmptyRetrievalError(
                    f"检索未返回任何文档，问题: '{question[:50]}'"
                )
            # 即使 raise_on_empty=False 也记录 warning，便于监控检索质量
            return RAGResponse(
                answer=self._empty_retrieval_response,
                sources=[],
                citations=[],
                retrieval_count=0,
            )

        # ===== 第3步：格式化文档 =====
        # 为什么这样做：LCEL 生成链需要 {context} 和 {question} 两个变量，
        #   format_docs 将 List[Document] 转为带编号的上下文字符串
        context = format_docs(docs)
        sources = [doc.metadata.get("source", "") for doc in docs]

        # ===== 第4步：LLM 生成（改造：带重试 + token 追踪） ======
        # 为什么改造：Task 1.7 需要自动重试和 token 使用量追踪
        # 改造方式：使用 self._retryable_invoke（带 tenacity 重试的 prompt|llm 链），
        #   返回 AIMessage，从中提取 token 使用量，再取 content 作为 answer
        generation_start = time.perf_counter()
        try:
            # 步骤 4a：带重试的 LLM 调用，返回 AIMessage
            # 为什么不用 self._generation_chain.invoke：
            #   1. 需要 AIMessage 以提取 token 使用量
            #   2. 需要在 LLM 层面加重试（不含 StrOutputParser）
            #   3. 重试逻辑由 tenacity 管理，异常时自动重试
            ai_message = self._retryable_invoke(
                {"context": context, "question": question}
            )
        except Exception as e:
            # 步骤 4b：异常处理（重试耗尽后到达此处）
            latency_ms = (time.perf_counter() - generation_start) * 1000
            logger.error(
                "LLM 调用失败（重试耗尽）",
                question=question[:50],
                error=str(e),
                error_type=type(e).__name__,
                latency_ms=round(latency_ms, 1),
            )
            raise LLMCallError(
                f"LLM 调用失败，问题: '{question[:50]}...': {e}",
                original_error=e,
                is_retryable=False,  # 重试耗尽后不再可重试
            ) from e

        generation_ms = (time.perf_counter() - generation_start) * 1000

        # 步骤 4c：提取 token 使用量
        # AIMessage 的 usage_metadata 是 LangChain 统一格式：
        #   {"input_tokens": 123, "output_tokens": 456, "total_tokens": 579}
        # response_metadata 是原始 SDK 返回的元数据（格式因提供商而异）
        usage = getattr(ai_message, "usage_metadata", None) or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)

        # 步骤 4d：提取回答文本
        # ai_message.content 等价于 StrOutputParser().invoke(ai_message)
        answer = ai_message.content

        logger.info(
            "生成完成",
            question=question[:50],
            answer_length=len(answer),
            latency_ms=round(generation_ms, 1),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

        # ===== 第5步：引用提取 =====
        # 为什么这样做：验证 LLM 生成的引用是否真实存在于检索结果中
        citations: List[ValidatedCitation] = []
        try:
            citations = self._citation_extractor.extract(answer, sources)
        except CitationExtractionError as e:
            # 引用提取失败不中断主流程，返回 citations=[] 的 RAGResponse
            logger.warning(
                "引用提取失败，跳过引用验证",
                error=str(e),
                question=question[:50],
            )

        # ===== 第6步：封装返回 =====
        total_ms = (time.perf_counter() - total_start) * 1000
        logger.info(
            "RAG 管道完成",
            question=question[:50],
            retrieval_count=len(docs),
            citation_count=len(citations),
            valid_citation_count=sum(1 for c in citations if c.is_valid),
            total_latency_ms=round(total_ms, 1),
        )

        return RAGResponse(
            answer=answer,
            sources=sources,
            citations=citations,
            retrieval_count=len(docs),
        )

    def stream(self, question: str) -> Iterator[str]:
        """流式生成：逐 token 返回文本流。

        流式 vs 同步的区别：
            invoke() → 等待全文本生成完毕 → 返回完整 RAGResponse
            stream() → 逐 token 推送 → 调用方实时展示（如 CLI 打字效果、SSE 推送）

        为什么流式不包含引用提取：
            引用提取需要完整文本才能执行（正则匹配需看全文），
            流式场景下文本是逐 token 产生的，无法提前提取引用。
            调用方可在流结束后调用 self.extract_citations() 获取引用。

        Args:
            question: 用户问题

        Yields:
            str: 逐 token 的文本片段
        """
        # ===== 第1步：检索 =====
        try:
            docs = self._retriever.invoke(question)
        except RetrievalError as e:
            logger.error("流式检索失败", question=question[:50], error=str(e))
            yield "[检索失败，请稍后重试]"
            return

        # ===== 第2步：空检索拦截 =====
        if not docs:
            logger.warning(
                "流式检索返回空结果", question=question[:50]
            )
            yield self._empty_retrieval_response
            return

        # ===== 第3步：格式化文档 =====
        context = format_docs(docs)

        # ===== 第4步：流式生成 =====
        # 为什么这样做：self._generation_chain.stream() 返回 Iterator[str]，
        #   StrOutputParser 在流式模式下逐 token 输出
        logger.info("开始流式生成", question=question[:50])
        try:
            for chunk in self._generation_chain.stream(
                {"context": context, "question": question}
            ):
                yield chunk
        except Exception as e:
            # 流式场景下调用方已在消费生成器，抛异常难以优雅处理
            # 改为 yield 错误提示文本
            logger.error(
                "流式生成失败",
                question=question[:50],
                error=str(e),
            )
            yield "\n\n[生成失败，请重试]"

    async def ainvoke(self, question: str) -> RAGResponse:
        """异步调用完整 RAG 管道（为 FastAPI 准备）。

        TODO(Task 4.5): 实现完整异步链路，当前先用同步 invoke 的结果包装
        为什么预留此方法：
            FastAPI 的 async def 路由需要异步调用链，
            当前用同步包装满足接口兼容性，Task 4.5 再优化为真异步。
        """
        # 当前实现：直接调用同步 invoke
        # Task 4.5 优化为：await self._generation_chain.ainvoke(...)
        return self.invoke(question)

    def retrieve(self, question: str) -> List[Document]:
        """仅执行检索步骤，返回文档列表。

        为什么暴露此方法：
            Task 2.2 的 LangGraph 检索节点只需检索，不需走完整 RAG 管道。
            暴露 retrieve 方法避免 LangGraph 重新实例化检索器。

        Args:
            question: 用户问题

        Returns:
            检索到的文档列表

        Raises:
            GenerationError: 检索失败时（包装 RetrievalError）
        """
        try:
            docs = self._retriever.invoke(question)
            logger.info(
                "独立检索完成",
                question=question[:50],
                doc_count=len(docs),
            )
            return docs
        except RetrievalError as e:
            raise GenerationError(
                f"检索失败，问题: '{question[:50]}...': {e}"
            ) from e

    def extract_citations(
        self, answer: str, sources: List[str]
    ) -> List[ValidatedCitation]:
        """从已生成的回答文本中提取并验证引用（供流式场景后置调用）。

        使用场景：
            1. 流式输出结束后，调用方需要验证引用
            2. LangGraph 生成节点需要将引用信息写入状态
            3. 评估模块需要统计引用命中率

        Args:
            answer: LLM 生成的完整回答文本
            sources: 检索结果的 source URL 列表

        Returns:
            验证后的引用列表
        """
        try:
            return self._citation_extractor.extract(answer, sources)
        except CitationExtractionError as e:
            logger.warning(
                "引用提取失败", error=str(e), answer_length=len(answer)
            )
            return []

    @classmethod
    def create(
        cls,
        persist_directory: str = "db/langchain_docs_db1",
        collection_name: str = "langchain_docs1",
        search_type: str = "similarity",
        search_kwargs: Optional[Dict[str, Any]] = None,
        prompt_version: PromptVersion = PromptVersion.V2,
        include_few_shot: bool = True,
        include_chat_history: bool = False,
    ) -> "RAGChain":
        """工厂方法：使用默认配置创建 RAGChain 实例。

        封装 retriever、llm、prompt 的创建细节，调用方只需一行代码即可创建链。

        为什么默认使用 V2 + few_shot：
            V2 的跨语言策略和严格引用格式规范配合 few-shot 示例，
            引用格式遵从度最高，适合生产级默认配置。
            V1 作为降级选项，在 V2 出现问题时快速切换。

        Args:
            persist_directory: Chroma 数据目录
            collection_name: Chroma 集合名称
            search_type: 检索类型
            search_kwargs: 检索参数（默认 k=5）
            prompt_version: Prompt 版本
            include_few_shot: 是否包含 few-shot 示例
            include_chat_history: 是否包含对话历史占位符

        Returns:
            配置好的 RAGChain 实例
        """
        # 第1步：创建检索器
        retriever = create_vector_retriever(
            persist_directory=persist_directory,
            collection_name=collection_name,
            search_type=search_type,
            search_kwargs=search_kwargs,
        )

        # 第2步：获取 LLM 实例（从 src.core.config 导入）
        llm = deepseek_llm

        # 第3步：创建 Prompt 模板
        prompt = get_prompt(
            prompt_version,
            include_few_shot=include_few_shot,
            include_chat_history=include_chat_history,
        )

        # 第4步：创建并返回 RAGChain 实例
        logger.info(
            "RAGChain 工厂创建",
            persist_directory=persist_directory,
            collection_name=collection_name,
            search_type=search_type,
            prompt_version=prompt_version.value,
            include_few_shot=include_few_shot,
        )

        return cls(retriever=retriever, llm=llm, prompt=prompt)