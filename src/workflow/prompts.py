"""Workflow 路径的 Prompt 模板与消息构建模块。

设计意图：
2. **消息构建**：build_generate_messages 替代 LCEL 的 prompt | llm chain，
   直接构建 list[BaseMessage] 后调用 llm.invoke(messages)
3. **版本管理**：通过 PromptVersion 枚举 + PROMPT_REGISTRY 管理多版本
4. **chat_history 精确语义**：接收 state["messages"][:-1]（排除当前轮
   原始 HumanMessage），避免当前问题重复出现在 LLM 输入中
"""

from enum import Enum
from typing import Dict, Iterable, List

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.documents import Document
from pydantic import BaseModel, Field

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
# Prompt 版本枚举
# ============================================================

class PromptVersion(str, Enum):
    """Prompt 版本枚举。

    为什么用 str + Enum（设计决策）：
        枚举值可同时作字符串比较和字典 key，便于配置切换。
        str 继承确保版本值可序列化、可做 JSON 配置字段。
    """
    V1 = "v1"   # 基础版：简洁指令，无 few-shot
    V2 = "v2"   # 增强版：含 few-shot 示例，引用格式遵从度更高


# ============================================================
# System Message 模板
# ============================================================

SYSTEM_TEMPLATE_V1 = """你是一个专业的技术文档问答助手。

## 角色定义
- 你基于提供的文档片段回答用户问题
- 回答必须使用中文，即使参考文档是英文

## 引用格式要求
- 在回答中使用 [1], [2] 等标记引用文档片段
- 在回答末尾列出"来源"部分，标明每个引用标记对应的文档 URL

## 幻觉防护
- 如果提供的文档片段不包含回答问题的信息，请如实回答："根据现有文档，我无法回答该问题。"
- 不要编造文档中不存在的信息"""

SYSTEM_TEMPLATE_V2 = """你是一个专业的技术文档问答助手，专门处理跨语言技术问答。

## 角色定义
- 你基于提供的英文文档片段回答用户的中文问题
- 回答必须使用中文，即使参考文档是英文
- 可以保留技术术语的英文原文（如 LangGraph、VectorStore），但解释需用中文

## 跨语言策略
- 用户可能用中文提问关于英文文档的内容
- 你需要理解中文问题，从英文文档中找到相关信息，然后用中文组织回答
- 技术概念翻译优先使用社区通行译法（如"向量存储"而非"矢量仓库"）

## 引用格式要求（严格遵守）
- 在回答中使用 [1], [2] 等行内标记引用文档片段
- 每个引用标记必须在回答末尾的"来源"部分有对应条目
- 来源格式：[N] URL（每个引用占一行）
- 示例：
  来源：
  [1] https://langchain-ai.github.io/langgraph/concepts/low_level/
  [2] https://langchain-ai.github.io/langgraph/how-tos/map_reduce/

## 幻觉防护（严格遵守）
- 如果提供的文档片段不包含回答问题的信息，请如实回答："根据现有文档，我无法回答该问题。"
- 不要编造文档中不存在的信息
- 不要使用你自己的知识库来补充答案，只基于提供的文档片段"""


# ============================================================
# Human Message 模板
# ============================================================

HUMAN_TEMPLATE_V1 = """参考文档：
{context}

问题：{question}"""

HUMAN_TEMPLATE_V2 = """参考文档：
{context}

问题：{question}

请基于以上参考文档回答问题，使用 [1], [2] 等标记引用，并在末尾列出来源。"""


# ============================================================
# Few-shot 示例
# ============================================================

FEW_SHOT_EXAMPLES: List[tuple] = [
    (
        HumanMessage(
            content="参考文档：\n"
                    "[1] LangGraph is a framework for building stateful, multi-actor "
                    "applications with LLMs. It extends LangChain with graph-based "
                    "workflow orchestration. "
                    "(source: https://langchain-ai.github.io/langgraph/concepts/low_level/)\n\n"
                    "[2] StateGraph is the core class in LangGraph. You define nodes "
                    "(functions) and edges (transitions) to build your agent workflow. "
                    "(source: https://langchain-ai.github.io/langgraph/how-tos/map_reduce/)\n\n"
                    "问题：LangGraph 是什么？它的核心类是什么？"
        ),
        AIMessage(
            content="LangGraph 是一个用于构建有状态、多参与者 LLM 应用的框架，"
                    "它通过基于图的工作流编排扩展了 LangChain[1]。"
                    "其核心类是 StateGraph，通过定义节点（函数）和边（转换）"
                    "来构建 Agent 工作流[2]。\n\n"
                    "来源：\n"
                    "[1] https://langchain-ai.github.io/langgraph/concepts/low_level/\n"
                    "[2] https://langchain-ai.github.io/langgraph/how-tos/map_reduce/"
        ),
    ),
]


# ============================================================
# 文档评估（Task 2.6）
# ============================================================

class DocumentGrade(BaseModel):
    """单篇文档的二元相关性评分。

    使用方法：作为 with_structured_output 的类型参数，
        llm.with_structured_output(DocumentGrade)

    为什么用 str "yes"/"no" 而非 bool：
        遵循 LangGraph 官方 Agentic RAG 教程模式。
        LLM 对字符串标签的输出稳定性高于 True/False——字符串匹配
        没有类型转换歧义，且 prompt 中的 'yes'/'no' 更自然。
    """
    binary_score: str = Field(
        description="Relevance score: 'yes' if relevant, or 'no' if not relevant"
    )


class GradeList(BaseModel):
    """批量文档评分结果 — 一次性返回所有文档的评分列表。

    [交叉验证] Plan agent 建议批量评分替代逐条调用的理由：
        - 延迟：N 条文档 × ~500ms → 1 × ~500ms
        - 跨文档关联偏差理论上存在但实践中影响极小
        - N = 5 时 2.5s vs 0.5s，差距在实际应用中不可接受
    """
    grades: list[DocumentGrade] = Field(
        description="Grades for each document, in the same order as input documents"
    )


GRADE_PROMPT = """You are a grader assessing relevance of a retrieved document to a user question.
The document may be written in English and the question may be in Chinese or English.
Grade based on semantic meaning and content relevance, not language match.

Here is the retrieved document:
{document}

Here is the user question:
{question}

If the document contains keyword(s) or semantic meaning related to the question, grade it as relevant.
Give a binary score 'yes' or 'no' to indicate whether the document is relevant to the question."""
"""文档评估 Prompt — 跨语言适配（英文文档 + 中文问题）。

为什么明确指定跨语言评估（设计决策）：
    默认情况下 LLM 可能认为"英文文档 ≠ 中文问题"即不相关，
    显式告知 grade based on semantic meaning not language match
    可避免这种误判。"""

REWRITE_PROMPT = """Look at the input and try to reason about the underlying semantic intent / meaning.
Here is the initial question:
{question}
Formulate an improved question that would be more effective for semantic search.
Keep the original intent unchanged."""
"""查询改写 Prompt — 来自 LangGraph 官方 Agentic RAG 教程适配。

核心约束：最小修改原则，只增不删，保留原始问题语义。"""


# ============================================================
# Prompt 版本注册表
# ============================================================

PROMPT_REGISTRY: Dict[PromptVersion, Dict[str, str]] = {
    PromptVersion.V1: {
        "system": SYSTEM_TEMPLATE_V1,
        "human": HUMAN_TEMPLATE_V1,
    },
    PromptVersion.V2: {
        "system": SYSTEM_TEMPLATE_V2,
        "human": HUMAN_TEMPLATE_V2,
    },
}


# ============================================================
# 消息构建函数（替代 LCEL prompt | llm chain）
# ============================================================

def build_generate_messages(
    *,
    context: str,
    question: str,
    chat_history: Iterable[BaseMessage],
    summary: str = "",
    version: PromptVersion = PromptVersion.V2,
    include_few_shot: bool = True,
) -> list[BaseMessage]:
    """构建生成节点的 LLM 输入消息列表。

    替代原 prompt | llm LCEL chain。generate_node 调此函数获取消息列表，
    然后直接调用 llm.invoke(messages)，不经过 ChatPromptTemplate。

    消息顺序（LangChain Chat 模型惯例）：
        1. SystemMessage — 全局行为指令
        2. [SystemMessage(摘要)] — Task 2.5 对话摘要（可选）
        3. [Few-shot 示例对] — Human + AI 示例（可选，V2 默认开启）
        4. chat_history — 前几轮的对话对（不含当前轮原始 HumanMessage）
        5. HumanMessage — 当前轮问题 + 文档上下文

    为什么 chat_history 接收 state["messages"][:-1]（精确语义）：
        state["messages"][-1] 是当前轮的原始 HumanMessage，而本函数
        已经通过 question + context 格式化为新的 HumanMessage。
        如果 chat_history 包含当前轮原始 HumanMessage，LLM 会看到两个
        Q_current，造成冗余和潜在混淆。

    为什么摘要用 SystemMessage 而非放在 chat_history（设计决策）：
        摘要描述的是对话的语义压缩，是 meta 信息而非对话记录。
        SystemMessage 区域适合放置 meta 信息，LLM 将其视为"对话上下文说明"。
        放在 chat_history 中会导致具体消息与摘要并列，LLM 不确定哪个更可信。

    Args:
        context: format_docs 格式化后的文档上下文字符串
        question: 当前用户问题（由 route_node 从 messages 中提取）
        chat_history: 前几轮消息列表（不含当前轮），即 state["messages"][:-1]
        summary: 对话摘要文本（Task 2.5 memory 节点写入），空字符串表示无摘要
        version: Prompt 版本，默认 V2
        include_few_shot: 是否插入 few-shot 示例（仅 V2 有效）

    Returns:
        可直接传入 llm.invoke() 的消息列表
    """
    # 步骤 1：获取当前版本的模板
    templates = PROMPT_REGISTRY[version]

    # 步骤 2：组装消息列表
    messages: list[BaseMessage] = []

    # 2a：SystemMessage — 全局行为指令，必须在首位
    messages.append(SystemMessage(content=templates["system"]))

    # 2b：摘要注入（Task 2.5）
    # 为什么放在 SystemMessage 之后、few-shot 之前：
    #   摘要是对对话历史的元描述，紧随系统指令后最自然——不让它干扰
    #   系统指令的全局性，又确保在 few-shot 示例之前被 LLM 关注
    if summary:
        messages.append(SystemMessage(
            content=(
                "以下是之前的对话摘要，请结合它理解当前对话的上下文：\n"
                f"{summary}\n\n"
                "注意：摘要是对之前对话的压缩，不是完整对话记录。"
            )
        ))

    # 2c：Few-shot 示例（可选）
    # 为什么放在 System 和 chat_history 之间（设计决策）：
    #   Chat 模型会模仿紧邻示例的格式，few-shot 在 chat_history 之前
    #   让模型先看到"理想回答格式"，再处理历史对话和当前问题
    if include_few_shot and version == PromptVersion.V2:
        for human_msg, ai_msg in FEW_SHOT_EXAMPLES:
            messages.append(human_msg)
            messages.append(ai_msg)

    # 2d：Chat history — 前几轮对话
    # 注意：此处接收的 chat_history 已排除 state["messages"][-1]
    # （当前轮原始 HumanMessage），防止问题重复
    messages.extend(chat_history)

    # 2e：HumanMessage — 当前轮问题 + 文档上下文
    # 为什么在列表末尾（设计决策）：
    #   Chat 模型的 attention 对末尾 token 权重更高，
    #   当前问题在末尾确保模型优先关注当前输入
    messages.append(HumanMessage(
        content=templates["human"].format(context=context, question=question)
    ))

    return messages

__all__ = [
    "build_generate_messages",
    "format_docs",
    "DocumentGrade",
    "GradeList",
    "REWRITE_PROMPT",
]
