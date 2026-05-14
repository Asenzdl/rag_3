"""条件边路由函数 — 根据状态决定图的执行路径。

本模块定义条件边的路由函数，这些函数读取 GraphState 中的特定字段，
返回下一跳节点名称。LangGraph 的 add_conditional_edges 使用这些函数
实现动态路由。

为什么路由函数独立为模块（设计决策）：
    1. 可测试性：路由函数是纯函数（state -> str），可独立测试
    2. 职责单一：edges.py 负责"路径选择"，builder.py 负责"图组装"
    3. 可替换性：Task 2.6 自适应路由可替换路由函数
"""

import structlog

from src.workflow.routing import FALLBACK, GREETING, RETRIEVE
from src.workflow.state import GraphState

logger = structlog.get_logger(__name__)


# ============================================================
# Phase 4 预留分支标签
# ============================================================

TOOL_CALL = "tool_call"
"""工具调用分支 — Phase 4 实现工具路由时使用。当前仅预注册节点名，不实现路由逻辑。"""


# ============================================================
# 条件边路由函数
# ============================================================

def route_after_classification(state: GraphState) -> str:
    """条件边路由函数：route 节点之后，根据 route_decision 决定下一跳。

    为什么是幂等函数（生产级注意事项）：
        给定相同的 state，此函数始终返回相同的标签。
        条件边的路由函数必须是幂等的——如果相同状态产生不同路由，
        会导致不可预测的执行路径和难以复现的 bug。

    为什么未知标签默认返回 FALLBACK 而非 RETRIEVE
    （与 classify_intent 的默认值不同）：
        classify_intent 默认 RETRIEVE 是"分类前的乐观回退"——
        还没分类就给检索一个机会。route_after_classification 默认 FALLBACK 是
        "分类后的保守回退"——route_node 已经尝试分类但产生了无效结果，
        说明分类流程出了问题，此时再走检索可能带着无效的 question 字段，
        不如直接降级。

    Args:
        state: 当前图状态

    Returns:
        下一跳节点名称："retrieve" / "greeting" / "fallback"
    """
    # 第1步：读取 route_decision
    decision = state.get("route_decision", "")

    # 第2步：匹配路由标签
    #   ├─ RETRIEVE → "retrieve"
    #   ├─ GREETING → "greeting"
    #   ├─ FALLBACK → "fallback"
    #   └─ 未知/空 → "fallback"（保守降级）
    if decision == RETRIEVE:
        return RETRIEVE
    if decision == GREETING:
        return GREETING
    if decision == FALLBACK:
        return FALLBACK

    # 未知/空标签 → 保守降级
    logger.warning(
        "未知路由决策，默认走降级路径",
        route_decision=decision,
    )
    return FALLBACK


# ============================================================
# Task 2.6 文档评估后路由
# ============================================================

def route_after_grade(state: GraphState) -> str:
    """条件边路由函数：grade 节点之后，根据文档相关性和重写次数决定下一跳。

    [交叉验证] 纯函数，非 closure，max_rewrite_count 从 state 直接读取。

    路由逻辑：
        - 有相关文档（documents 非空）→ "memory"（正常生成）
        - 无相关文档 + rewrite_count < max_rewrite_count → "rewrite"
        - 无相关文档 + rewrite_count >= max_rewrite_count → "memory"（降级）

    Args:
        state: 当前图状态，需包含 documents、rewrite_count、max_rewrite_count

    Returns:
        下一跳节点名称："memory" / "rewrite"
    """
    docs = state.get("documents", [])
    count = state.get("rewrite_count", 0)
    max_count = state.get("max_rewrite_count", 1)

    if docs:
        return "memory"

    if count < max_count:
        return "rewrite"

    return "memory"  # 降级：generate 节点处理空文档场景

__all__ = [
    "route_after_classification",
    "route_after_grade",
]
