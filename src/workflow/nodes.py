"""LangGraph 工作流节点函数 — 路由、检索、生成。

本模块定义三个核心节点函数，通过工厂闭包模式注入依赖。
Task 2.3 的 builder 调用 create_workflow_nodes 获取节点字典，
直接用于 graph.add_node(name, func) 注册。

核心设计：
1. **工厂闭包注入依赖**：节点函数不直接导入 config/factories，
   依赖通过 create_workflow_nodes 参数注入，支持 Mock 测试。
2. **节点职责单一**：每个节点只做一件事——路由节点只做意图分类，
   检索节点只做检索，生成节点只做生成。
3. **优雅降级**：每个节点捕获已知异常，返回错误状态更新，
   避免未处理异常崩溃整个图。
"""

import time
from typing import Any, Callable

import structlog
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from src.memory import (
    KEEP_LAST_N,
    summarize_conversation,
    trim_conversation_history,
)
from src.workflow.citation import CitationExtractor, CitationExtractionError
from src.utils.retry import with_retry
from src.retriever.base_retriever import RetrievalError
from src.retriever.protocols import RetrieverProtocol
from src.workflow.prompts import (
    DocumentGrade,
    GradeList,
    REWRITE_PROMPT,
    build_generate_messages,
    format_docs,
)
from src.workflow.routing import classify_intent
from src.workflow.state import GraphState
from langgraph.runtime import Runtime
from .state import GraphContext

logger = structlog.get_logger(__name__)


# ============================================================
# 节点级常量
# ============================================================

EMPTY_RETRIEVAL_RESPONSE = (
    "抱歉，我在文档库中未找到与您问题相关的内容。"
    "请尝试换个方式提问，或确认您的问题与文档主题相关。"
)
"""空检索预设回复 — 与 RAGChain.EMPTY_RETRIEVAL_RESPONSE 措辞一致。

为什么不从 RAGChain 导入（反直觉辩护）：
    workflow 不应依赖 generation 模块（模块分离原则）。
    RAGChain 的常量是其内部实现细节，workflow 节点独立定义
    避免引入不必要的模块间依赖。两者措辞一致是当前决策，
    未来可能因节点上下文不同而分化。"""

GENERATION_ERROR_RESPONSE = (
    "抱歉，生成回答时遇到了问题，请稍后重试。"
)
"""生成失败预设回复 — LLM 调用失败时的降级响应。"""


# ============================================================
# 工厂函数：创建工作流节点
# ============================================================

def create_workflow_nodes(
    retriever: RetrieverProtocol,
    llm: BaseChatModel,
    citation_extractor: CitationExtractor | None = None,
) -> dict[str, Callable[..., dict]]:
    """创建工作流节点函数（工厂函数，闭包模式注入依赖）。

    为什么用工厂闭包而非模块级导入（设计决策）：
        详见 design.md 决策 1。核心理由：核心逻辑可 Mock，依赖可注入。

    Args:
        retriever: 检索器（满足 RetrieverProtocol 即可，可 Mock）
        llm: Chat 模型实例（路由和生成共用，可 Mock）
        citation_extractor: 引用提取器，默认创建正则策略实例

    Returns:
        {"route": route_node, "retrieve": retrieve_node, "generate": generate_node}
    """
    # 第1步：初始化依赖
    _citation_extractor = citation_extractor or CitationExtractor()

    # 第2步：创建带重试的 invoke 函数（包装 llm.invoke 而非 prompt | llm chain）
    # 为什么用 lambda msgs: llm.invoke(msgs) 而非直接传 llm.invoke（设计决策）：
    #   with_retry 要求 callable 参数不含 self 引用（llm.invoke 是绑定方法），
    #   直接传 llm.invoke 会导致序列化问题。lambda 是轻量闭包，无此限制。
    # 为什么入参是 list[BaseMessage]（设计决策）：
    #   与 LangGraph 官方模式一致——LLM 的输入输出都是 messages，没有 dict 中间层。
    retryable_invoke = with_retry(
        lambda msgs: llm.invoke(msgs), max_attempts=3, min_wait=4, max_wait=10,
    )

    # ============================================================
    # route_node：意图分类 + 提取当前问题
    # ============================================================

    def route_node(state: GraphState) -> dict:
        """路由节点：意图分类 + 提取当前问题。

        为什么同时写 question 和 route_decision（设计决策）：
            question 独立于 messages 是 Task 2.1 的设计决策。
            route_node 是唯一写入 question 的节点——后续节点直接读取，
            无需关心 messages 的内部结构。

        异常处理：
            LLM 分类失败 → 默认 "retrieve"（详见 classify_intent 的反直觉辩护）

        Returns:
            {"question": str, "route_decision": str}
        """
        # 第1步：从 messages 中提取最新用户问题
        # 反向遍历 state["messages"]，找到最后一条 HumanMessage
        question = ""
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, HumanMessage):
                question = msg.content
                break

        if not question:
            logger.warning(
                "messages 中未找到 HumanMessage，question 为空",
            )

        logger.info("提取用户问题", question=question[:50])

        # 第2步：调用 classify_intent 分类意图
        route_decision = classify_intent(question, llm)
        logger.info("路由决策", route_decision=route_decision, question=question[:50])

        # 第3步：返回状态更新
        return {"question": question, "route_decision": route_decision}

    # ============================================================
    # retrieve_node：调用检索器获取相关文档
    # ============================================================

    def retrieve_node(state: GraphState) -> dict:
        """检索节点：调用检索器获取相关文档。

        为什么直接调用 retriever.invoke() 而非 RAGChain.retrieve()（设计决策）：
            RAGChain.retrieve() 将 RetrievalError 包装为 GenerationError，
            这是为 RAGChain 编排层设计的异常转换。LangGraph 节点需要更细粒度
            的异常控制——检索失败时返回空文档列表，让 generate 节点处理
            "空检索"场景。

        为什么空文档不设置 route_decision="fallback"（反直觉辩护）：
            详见 design.md 决策 2。route_decision 是路由节点的专属输出，
            retrieve_node 不应覆写。

        Returns:
            {"documents": List[Document]}
        """
        question = state.get("question", "")
        logger.info("开始检索", question=question[:50])

        # 第2步：调用检索器 + 异常处理
        try:
            docs = retriever.invoke(question)
        except RetrievalError as e:
            logger.error(
                "检索失败",
                question=question[:50],
                error=str(e),
            )
            docs = []  # 鲁棒性：回退为空列表，让 generate 节点处理
        except Exception as e:
            logger.error(
                "检索发生未预期异常",
                question=question[:50],
                error=str(e),
                error_type=type(e).__name__,
            )
            docs = []

        logger.info("检索完成", question=question[:50], doc_count=len(docs))

        # 第3步：返回状态更新
        return {"documents": docs}

    # ============================================================
    # grade_documents_node：文档相关性评估（Task 2.6）
    # ============================================================

    def grade_documents_node(state: GraphState) -> dict:
        """文档评估节点：批量评分 + 过滤不相关文档。

        [交叉验证] 批量评分（GradeList）替代逐条评分，延迟 5x → 1x。

        工作流程：
            1. 读取 state.question、state.documents
            2. 调用 llm.with_structured_output(GradeList) 批量评分
            3. 保留 binary_score == "yes" 的文档
            4. 失败时保守回退：保留所有文档

        Returns:
            {"documents": list[Document]} — 过滤后的文档列表
        """
        question = state.get("question", "")
        docs = state.get("documents", [])

        if not docs:
            return {}

        # 第1步：组装批量评分 prompt
        doc_texts = "\n\n".join(
            f"[{i+1}] {d.page_content}" for i, d in enumerate(docs)
        )
        grade_prompt = (
            "You are a grader assessing relevance of retrieved documents to a user question.\n"
            "The documents may be written in English and the question may be in Chinese or English.\n"
            "Grade based on semantic meaning and content relevance, not language match.\n\n"
            f"Question: {question}\n\n"
            f"Documents:\n{doc_texts}\n\n"
            "For each document, return a binary score 'yes' if relevant or 'no' if not, "
            "in the same order as the documents."
        )

        # 第2步：调用 LLM 评分
        try:
            grade_chain = llm.with_structured_output(GradeList)
            result = grade_chain.invoke(
                [HumanMessage(content=grade_prompt)]
            )

            # 第3步：验证返回结果长度
            if len(result.grades) != len(docs):
                logger.warning(
                    "评分结果数量不匹配，保守保留所有文档",
                    expected=len(docs),
                    actual=len(result.grades),
                )
                return {"documents": docs}

            # 第4步：仅保留 "yes" 的文档
            filtered = [
                doc
                for doc, grade in zip(docs, result.grades)
                if grade.binary_score.strip().lower() == "yes"
            ]
            logger.info(
                "文档评分完成",
                input_count=len(docs),
                output_count=len(filtered),
            )
            return {"documents": filtered}

        except Exception as e:
            logger.warning(
                "文档评分失败，保守保留所有文档",
                error=str(e),
                error_type=type(e).__name__,
            )
            return {"documents": docs}

    # ============================================================
    # rewrite_node：查询改写（Task 2.6）
    # ============================================================

    def rewrite_node(state: GraphState) -> dict:
        """查询改写节点：改写问题以提升检索效果。

        [交叉验证] rewrite_count 在此递增（而非 grade 节点）：
            条件边需在 rewrite 前判断 count < max 才能放行，
            若 grade 已递增，条件边看到的是 post-increment 值。

        Returns:
            {"question": str, "rewrite_count": int}
        """
        question = state.get("question", "")
        current_count = state.get("rewrite_count", 0)

        if not question:
            return {"rewrite_count": current_count + 1}

        try:
            response = llm.invoke(
                [HumanMessage(content=REWRITE_PROMPT.format(question=question))]
            )
            rewritten = response.content.strip()
            if not rewritten:
                rewritten = question
        except Exception as e:
            logger.warning(
                "查询改写失败，保留原问题",
                error=str(e),
                error_type=type(e).__name__,
            )
            rewritten = question

        return {
            "question": rewritten,
            "rewrite_count": current_count + 1,
        }

    # ============================================================
    # generate_node：LLM 生成回答 + 引用提取 + 迭代计数
    # ============================================================

    def generate_node(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
        """生成节点：调用 LLM 生成回答 + 引用提取 + 迭代计数。

        为什么同时递增 iteration_count 和写 messages（设计决策）：
            iteration_count 是安全阀的输入（Task 2.3 条件边检查），
            messages 是对话历史的累积。两者是不同维度的状态更新：
            - iteration_count: 控制流（防止无限循环）
            - messages: 数据流（对话内容）

        为什么空文档时不调用 LLM（功能取舍）：
            空检索意味着没有相关上下文，调用 LLM 既浪费 API 配额，
            又增加幻觉风险。直接返回预设回复更安全、更经济。

        异常处理：
            LLM 调用失败 → 返回错误 AIMessage + 递增 iteration_count
            引用提取失败 → 降级为无引用的回答（不中断主流程）

        Returns:
            {"messages": [AIMessage], "iteration_count": int}
        """
        # 第1步：读取状态
        question = state.get("question", "")
        documents = state.get("documents", [])
        current_count = state.get("iteration_count", 0)
        max_iterations = runtime.context.max_iterations if runtime.context is not None else 3

        # 第2步：空检索拦截
        #   ├─ documents 为空 → 返回空检索预设回复 + 递增计数器
        #   └─ documents 非空 → 继续步骤 3
        if not documents:
            logger.warning("空检索拦截，返回预设回复", question=question[:50])
            return {
                "messages": [AIMessage(content=EMPTY_RETRIEVAL_RESPONSE)],
                "iteration_count": current_count + 1,
            }

        # 第3步：格式化文档 + 提取来源
        context = format_docs(documents)
        sources = [doc.metadata.get("source", "") for doc in documents]

        # 第4步：通过 build_generate_messages 构建消息列表后调用 LLM
        # 为什么用 build_generate_messages + direct llm.invoke 而非 prompt | llm（设计决策）：
        #   与 LangGraph 官方模式对齐——messages 是 LLM 输入的唯一载体。
        #   Task 2.5 记忆管理直接操作 state["messages"]，处理后自然流入 chat_history，
        #   无需 chat_history 桥接层。
        # chat_history 传入 state["messages"][:-1]（排除当前轮原始 HumanMessage），
        # 因为当前轮问题已由 question + context 格式化为新的 HumanMessage。
        messages = build_generate_messages(
            context=context,
            question=question,
            chat_history=state.get("messages", [])[:-1],
            summary=state.get("summary", ""),
        )
        # 为什么用 except Exception 统一捕获（反直觉辩护）：
        #     with_retry(reraise=True) 重抛原始 SDK 异常（如 openai.APITimeoutError），
        #     不是 LLMCallError。统一捕获 Exception + 日志记录 error_type
        #     保留了诊断信息，避免对特定 SDK 异常类型的依赖。
        start = time.perf_counter()
        try:
            ai_message = retryable_invoke(messages)
            answer = ai_message.content

            # 提取 token 使用量（与 RAGChain._generate_step 一致）
            usage = getattr(ai_message, "usage_metadata", None) or {}
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

            latency_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "生成完成",
                question=question[:50],
                answer_length=len(answer),
                latency_ms=round(latency_ms, 1),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "生成失败",
                question=question[:50],
                error=str(e),
                error_type=type(e).__name__,
                latency_ms=round(latency_ms, 1),
            )
            answer = GENERATION_ERROR_RESPONSE

        # 第5步：引用提取（非致命，失败降级为空列表）
        try:
            citations = _citation_extractor.extract(answer, sources)
            logger.info(
                "引用提取完成",
                citation_count=len(citations),
                valid_count=sum(1 for c in citations if c.is_valid),
            )
        except CitationExtractionError as e:
            logger.warning("引用提取失败，跳过引用验证", error=str(e))
        # 注意：当前 Task 不将 citations 写入状态（GraphState 无此字段），
        #       提取结果仅用于日志记录。
        # TODO(Task 2.6): 评估是否需在状态中增加 citations 字段

        # 第6步：组装返回
        answer_message = AIMessage(content=answer)
        return {
            "messages": [answer_message],
            "iteration_count": current_count + 1,
        }

    # ============================================================
    # memory_node：对话记忆管理（Task 2.5）
    # ============================================================

    def memory_node(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
        """记忆管理节点：检查消息长度，必要时触发裁剪或摘要。

        memory_node 执行时 state["messages"] 包含：
            [系统指令, 历史消息..., HumanMessage(当前轮)]
        当前轮 HumanMessage（即 messages[-1]）必须保留——memory 只压缩历史。

        memory_node 只写 messages 和 summary 字段，不碰 question / documents
        / route_decision / iteration_count（SRP——它们由其他节点管理）。

        Returns:
            {"messages": [RemoveMessage(...), ...], "summary": "..."} 或 {}
            返回 {} 表示无操作（不触发记忆管理）。
        """
        # 步骤 1：读取状态 + 配置
        messages = state.get("messages", [])
        max_tokens = (
            runtime.context.max_tokens
            if runtime.context is not None
            else 4000
        )
        if not messages:
            return {}
        # 日志：debug 记录当前消息数

        # 步骤 2：计算 token 总数，判断是否超限
        # count_tokens_approximately 接收 list[BaseMessage] 而非单条消息
        total = count_tokens_approximately(messages)
        if total <= max_tokens:
            logger.debug("消息列表未超阈值，跳过记忆管理")
            return {}
        logger.info(
            "触发记忆管理",
            message_count=len(messages),
            total_tokens=total,
            max_tokens=max_tokens,
        )

        # 步骤 3：尝试摘要（增量扩展）
        #   ├─ 成功 → 步骤 4（摘要成功路径）
        #   └─ 失败 → 步骤 5（降级路径）
        try:
            new_summary, kept = summarize_conversation(
                messages=messages,
                llm=llm,
                existing_summary=state.get("summary", ""),
                keep_last_n=KEEP_LAST_N,
            )
            # 防 LLM 返回空 content 清除已有摘要
            if not new_summary:
                new_summary = state.get("summary", "") or ""
        except Exception as e:
            logger.error("摘要失败，降级为裁剪", error=str(e))
            # 降级：用 max_tokens * 0.9 防 end_on overshoot
            kept = trim_conversation_history(
                messages, max_tokens=int(max_tokens * 0.9)
            )
            # REMOVE_ALL_MESSAGES 清除所有旧消息，再重建 kept 列表
            # 为什么必须这样（反直觉辩护）：
            #   当前 LangChain 版本中消息的 id 属性为 None，
            #   无法通过 RemoveMessage(id=m.id) 按 ID 删除。
            #   REMOVE_ALL_MESSAGES 是框架层面可用的删除全部消息方式。
            logger.warning(
                "降级裁剪完成",
                kept_count=len(kept),
            )
            return {
                "messages": [
                    RemoveMessage(id=REMOVE_ALL_MESSAGES),
                    *kept,
                ],
            }

        # 步骤 4：摘要成功 — 全量重建消息列表
        # 用 REMOVE_ALL_MESSAGES 清除所有旧消息，再将 kept 重新写入
        # 注意：kept 是原对象引用，重新 append 时消息内容不变
        logger.info(
            "摘要完成",
            new_summary_length=len(new_summary),
            kept_count=len(kept),
        )
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *kept,
            ],
            "summary": new_summary,
        }

    # ============================================================
    # 返回节点字典
    # ============================================================

    # 返回节点字典
    return {
        "route": route_node,
        "retrieve": retrieve_node,
        "grade": grade_documents_node,
        "rewrite": rewrite_node,
        "memory": memory_node,
        "generate": generate_node,
    }

__all__ = [
    "create_workflow_nodes",
]
