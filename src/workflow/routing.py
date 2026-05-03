"""路由逻辑模块 — 意图分类与路由决策。

本模块将路由逻辑从节点函数中分离，独立管理意图分类的 Prompt 和分类函数。

为什么路由逻辑独立为模块（设计决策）：
    1. 可测试性：classify_intent 可独立测试，无需构造完整 GraphState
    2. 可替换性：Task 2.6 自适应路由可替换此模块的 classify_intent，
       节点函数无需修改（依赖注入的是函数引用，不是模块）
    3. 职责单一：routing.py 负责"分类逻辑"，nodes.py 负责"状态管理"
"""

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)

logger = structlog.get_logger(__name__)


# ============================================================
# 路由标签常量
# ============================================================

# 与 GraphState.route_decision 的可能值严格对齐
RETRIEVE = "retrieve"    # 知识库问题 → 进入检索流程
GREETING = "greeting"    # 问候类 → 直接回复
FALLBACK = "fallback"    # 无法回答 → 降级处理
VALID_ROUTE_DECISIONS = (RETRIEVE, GREETING, FALLBACK)


# ============================================================
# 路由分类 Prompt
# ============================================================

# System Message：定义分类任务 + 分类规则 + 输出格式约束
ROUTE_SYSTEM_TEMPLATE = """你是一个意图分类器。根据用户的输入，判断其意图类别。

分类规则：
- greeting：问候、寒暄（如"你好"、"早上好"、"hi"）
- retrieve：知识库问题（技术文档相关的问题，需要检索文档来回答）
- fallback：无法回答的问题（与文档主题无关、超出知识库范围的闲聊或问题）

请只返回类别标签（greeting、retrieve、fallback），不要返回其他内容。"""

# Human Message：用户问题占位
ROUTE_HUMAN_TEMPLATE = "{question}"


# ============================================================
# Prompt 工厂函数
# ============================================================

def create_route_prompt() -> ChatPromptTemplate:
    """创建路由分类 Prompt 模板。

    为什么是函数而非模块级变量（替代方案排除）：
        ChatPromptTemplate.from_messages 每次调用创建新实例，
        避免共享状态问题。与 generation/prompts.py 的 get_prompt 模式一致。
    """
    return ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(ROUTE_SYSTEM_TEMPLATE),
        HumanMessagePromptTemplate.from_template(ROUTE_HUMAN_TEMPLATE),
    ])


# ============================================================
# 意图分类函数
# ============================================================

def classify_intent(question: str, llm: BaseChatModel) -> str:
    """使用 LLM 对用户问题进行意图分类。

    为什么是独立函数而非 route_node 的一部分（设计决策）：
        1. 可测试性：可独立测试分类逻辑，无需构造完整 GraphState
        2. 可替换性：Task 2.6 自适应路由可替换此函数为更复杂的分类器
        3. 职责单一：route_node 负责"状态管理"（提取问题+写入决策），
           classify_intent 负责"分类逻辑"（调用 LLM+解析结果）

    为什么默认返回 "retrieve" 而非 "fallback"（反直觉辩护）：
        分类失败时，默认 "retrieve" 让系统有机会检索相关文档——
        即使检索为空，generate 节点也能返回有意义的空检索回复。
        默认 "fallback" 则直接放弃，用户无法获得任何有用信息。
        "宁可多走一步检索，也不直接放弃"是生产级系统的保守策略。

    Args:
        question: 用户问题
        llm: Chat 模型实例

    Returns:
        路由标签："retrieve" / "greeting" / "fallback"

    Raises:
        无 — 所有异常内部处理，保证返回有效标签
    """
    # 第1步：创建路由 Prompt 模板 + 组装 LCEL 链
    prompt = create_route_prompt()
    chain = prompt | llm | StrOutputParser()

    # 第2步：调用链获取分类结果（异常安全：捕获所有异常 → 默认 RETRIEVE）
    try:
        raw_result = chain.invoke({"question": question})
        logger.debug("意图分类原始结果", raw_result=raw_result)
    except Exception as e:
        logger.warning(
            "意图分类 LLM 调用失败，默认走检索路径",
            question=question[:50],
            error=str(e),
        )
        return RETRIEVE

    # 第3步：解析 LLM 输出
    #   ├─ 去除首尾空白 + 转小写 → 在 VALID_ROUTE_DECISIONS 中 → 返回标签
    #   ├─ 不在有效列表 → 尝试子串匹配（处理 LLM 输出多余文本的情况）
    #   └─ 子串匹配失败 → 默认返回 RETRIEVE
    normalized = raw_result.strip().lower()

    # 第3a步：精确匹配
    if normalized in VALID_ROUTE_DECISIONS:
        return normalized

    # 第3b步：子串匹配 — 处理 "The intent is: retrieve" 等格式
    for valid_label in VALID_ROUTE_DECISIONS:
        if valid_label in normalized:
            logger.debug(
                "意图分类子串匹配",
                raw_result=raw_result,
                matched_label=valid_label,
            )
            return valid_label

    # 第3c步：无法识别 → 默认 RETRIEVE
    logger.warning(
        "意图分类结果无法识别，默认走检索路径",
        raw_result=raw_result,
        question=question[:50],
    )
    return RETRIEVE


__all__ = [
    "FALLBACK",
    "GREETING",
    "RETRIEVE",
    "VALID_ROUTE_DECISIONS",
    "classify_intent",
    "create_route_prompt",
]
