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

5. **依赖倒置**：retriever 参数类型为 RetrieverProtocol（协议），而非 VectorRetriever（具体），
   任何实现了 invoke(self, query: str) -> List[Document] 的对象均可注入。

使用示例：
    # 快速启动（推荐方式）
    from src.core.config import settings
    from src.core.factories import create_rag_chain

    chain = create_rag_chain(settings)
    result = chain.invoke("LangGraph 是什么？")
    print(result.answer)
    print(result.citations)

    # 流式输出
    for chunk in chain.stream("LangGraph 是什么？"):
        print(chunk, end="", flush=True)

    # 自定义配置（依赖注入）
    from src.core.factories import create_retriever, create_llm
    from src.generation.prompts import get_prompt, PromptVersion

    retriever = create_retriever(settings, search_kwargs={"k": 3})
    llm = create_llm("deepseek", settings)
    prompt = get_prompt(PromptVersion.V1)
    chain = RAGChain(retriever=retriever, llm=llm, prompt=prompt)
"""

import time
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Iterator, List, Optional

import structlog
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.generation.citation_chain import CitationExtractor, ValidatedCitation
from src.generation.exceptions import (
    CitationExtractionError,
    EmptyRetrievalError,
    GenerationError,
    LLMCallError,
)
from src.retriever.base_retriever import RetrievalError
from src.retriever.protocols import RetrieverProtocol
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
        retriever: RetrieverProtocol,
        llm: BaseChatModel,
        prompt: ChatPromptTemplate,
        citation_extractor: Optional[CitationExtractor] = None,
        empty_retrieval_response: str = EMPTY_RETRIEVAL_RESPONSE,
        raise_on_empty: bool = False,
    ):
        """初始化 RAGChain。

        Args:
            retriever: 检索器实例（满足 RetrieverProtocol 协议即可）
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

    # ============================================================
    # 私有步骤方法
    # ============================================================

    def _retrieve_step(self, question: str) -> List[Document]:
        """共享检索步骤 — 被 invoke/retrieve/stream 复用。

        为什么是私有方法而非独立函数（设计决策）：
            1. 步骤函数仅在 RAGChain 内部使用，Phase 2 LangGraph 节点直接调用底层组件
            2. 私有方法保持类的内聚性——步骤访问 self._retriever 实例属性
            3. format_docs() 是独立函数，因为 Phase 2 生成节点需跨模块复用

        为什么保留 RetrievalError 而不包装（反直觉辩护）：
            三个调用方对检索异常的处理策略不同：
            invoke() → 包装为 GenerationError
            retrieve() → 包装为 GenerationError
            stream() → yield 错误提示文本
            步骤方法若内部包装，调用方无法做差异化处理。

        注意点：此方法不包含空检索拦截逻辑——空检索是编排层决策（是否 raise_on_empty），
        不是检索步骤的职责。

        Args:
            question: 用户问题

        Returns:
            检索到的文档列表

        Raises:
            RetrievalError: 检索过程中发生异常（保留原始语义，由调用方决定包装方式）
        """
        start = time.perf_counter()
        docs = self._retriever.invoke(question)
        latency_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "检索完成",
            question=question[:50],
            doc_count=len(docs),
            latency_ms=round(latency_ms, 1),
        )
        return docs

    def _generate_step(self, context: str, question: str) -> str:
        """LLM 生成步骤 — 带重试调用 + token 追踪 + 异常包装。

        为什么返回 str 而非 tuple[str, dict]（功能取舍）：
            当前 token usage 仅用于日志，步骤方法内部记录即可。
            若 Task 4.6 需暴露 token 数据给 Prometheus，届时再调整返回类型。

        为什么步骤内包装为 LLMCallError 而非保留原始异常（设计决策）：
            LLMCallError 的 is_retryable 属性需要重试耗尽的上下文来判断，
            编排层不具备此上下文。若由编排层包装，需理解每种 SDK 异常类型，
            切换 LLM 提供商时需同时修改编排层。

        为什么 stream() 不复用此方法（替代方案排除）：
            stream() 使用 _generation_chain.stream() 逐 token yield，
            语义完全不同（yield vs return），强行共享需引入回调或生成器协议，
            复杂度远超收益。

        Args:
            context: 格式化后的文档上下文字符串
            question: 用户问题

        Returns:
            LLM 生成的回答文本

        Raises:
            LLMCallError: LLM 调用失败时（重试耗尽后包装为 is_retryable=False）
        """
        start = time.perf_counter()
        try:
            ai_message = self._retryable_invoke(
                {"context": context, "question": question}
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
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
                is_retryable=False,
            ) from e

        latency_ms = (time.perf_counter() - start) * 1000

        # 提取 token 使用量（LangChain 统一格式）
        usage = getattr(ai_message, "usage_metadata", None) or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)

        answer = ai_message.content

        logger.info(
            "生成完成",
            question=question[:50],
            answer_length=len(answer),
            latency_ms=round(latency_ms, 1),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
        return answer

    def _extract_citations_step(
        self, answer: str, sources: List[str]
    ) -> List[ValidatedCitation]:
        """引用提取步骤 — 非致命异常降级为空列表。

        为什么返回空列表而非抛异常（反直觉辩护）：
            引用提取是增强功能，回答文本本身仍然有效。
            调用方（CLI/FastAPI）更关心回答内容，引用缺失不应导致整个请求失败。

        Args:
            answer: LLM 生成的回答文本
            sources: 检索命中的文档 source URL 列表

        Returns:
            验证后的引用列表。提取失败返回空列表。
        """
        start = time.perf_counter()
        try:
            citations = self._citation_extractor.extract(answer, sources)
        except CitationExtractionError as e:
            logger.warning(
                "引用提取失败，跳过引用验证",
                error=str(e),
                question=answer[:50],
            )
            return []

        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "引用提取完成",
            citation_count=len(citations),
            valid_count=sum(1 for c in citations if c.is_valid),
            latency_ms=round(latency_ms, 1),
        )
        return citations

    # ============================================================
    # 公共编排方法
    # ============================================================

    def invoke(self, question: str) -> RAGResponse:
        """同步调用完整 RAG 管道（编排方法）。

        编排流程：检索 → 空检索拦截 → 格式化文档 → LLM 生成 → 引用提取 → 封装返回。
        每个步骤的实现细节封装在私有方法中，invoke() 仅负责调用和组装结果。

        Args:
            question: 用户问题（中文）

        Returns:
            RAGResponse 包含回答、来源、引用验证结果

        Raises:
            LLMCallError: LLM 调用失败时（包装底层 API 异常）
            EmptyRetrievalError: raise_on_empty=True 且检索为空时
            GenerationError: 检索阶段失败时
        """
        total_start = time.perf_counter()

        # 第1步：检索 — 共享步骤方法，编排层统一包装异常
        try:
            docs = self._retrieve_step(question)
        except RetrievalError as e:
            raise GenerationError(
                f"检索阶段失败，问题: '{question[:50]}...': {e}"
            ) from e

        # 第2步：空检索拦截 — 编排层决策（是否 raise_on_empty）
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
            return RAGResponse(
                answer=self._empty_retrieval_response,
                sources=[],
                citations=[],
                retrieval_count=0,
            )

        # 第3步：格式化文档 + 提取来源
        context = format_docs(docs)
        sources = [doc.metadata.get("source", "") for doc in docs]

        # 第4步：LLM 生成 — _generate_step 内部包装 LLMCallError
        answer = self._generate_step(context, question)

        # 第5步：引用提取 — _extract_citations_step 内部降级为空列表
        citations = self._extract_citations_step(answer, sources)

        # 第6步：封装返回
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

        为什么复用 _retrieve_step 但生成步骤独立实现：
            _retrieve_step 无副作用（纯查询），可安全复用。
            生成步骤语义不同（yield vs return），强行共享需引入回调，
            复杂度远超收益。

        Args:
            question: 用户问题

        Yields:
            str: 逐 token 的文本片段
        """
        # 第1步：检索 — 复用共享步骤方法
        try:
            docs = self._retrieve_step(question)
        except RetrievalError as e:
            logger.error("流式检索失败", question=question[:50], error=str(e))
            yield "[检索失败，请稍后重试]"
            return

        # 第2步：空检索拦截
        if not docs:
            logger.warning(
                "流式检索返回空结果", question=question[:50]
            )
            yield self._empty_retrieval_response
            return

        # 第3步：格式化文档
        context = format_docs(docs)

        # 第4步：流式生成 — 独立实现（_generation_chain.stream 逐 token yield）
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
        """异步调用完整 RAG 管道（占位，Task 4.5 应独立评估）。

        为什么用 NotImplementedError 而非假异步（反直觉辩护）：
            当前 ainvoke() 内部调用同步 invoke()，这是"假异步"——
            async def 中调用同步阻塞函数会阻塞事件循环，导致所有协程挂起。
            这比 NotImplementedError 更危险，因为调用方无法从类型签名
            判断行为是否真正异步。NotImplementedError 诚实告知"此功能未实现"，
            避免假异步的隐蔽风险。

        当前为占位，后续 Task 4.5 应独立评估异步链路实现。
        """
        raise NotImplementedError(
            "ainvoke 尚未实现。当前为占位，Task 4.5 应独立评估异步链路实现。"
        )

    def retrieve(self, question: str) -> List[Document]:
        """仅执行检索步骤，返回文档列表。

        为什么暴露此方法：
            Task 2.2 的 LangGraph 检索节点只需检索，不需走完整 RAG 管道。
            暴露 retrieve 方法避免 LangGraph 重新实例化检索器。

        为什么改用 _retrieve_step()（设计决策）：
            消除 retrieve() 和 invoke() 中的检索异常处理逻辑重复。
            两者都调用 _retrieve_step()，都在编排层捕获 RetrievalError → GenerationError。

        Args:
            question: 用户问题

        Returns:
            检索到的文档列表

        Raises:
            GenerationError: 检索失败时（包装 RetrievalError）
        """
        try:
            return self._retrieve_step(question)
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

__all__ = [
    "RAGChain",
    "RAGResponse",
    "format_docs",
]
