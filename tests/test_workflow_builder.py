"""工作流图构建测试 — 条件边路由函数 + 终端节点 + build_graph 编译与端到端验证。

测试覆盖：
1. route_after_classification：retrieve / greeting / fallback → 正确节点名
2. route_after_classification：空字符串 / 未知标签 → fallback（默认降级）
3. _greeting_node：返回问候预设回复
4. _fallback_node：返回降级预设回复
5. build_graph：编译成功，包含 5 个业务节点
6. build_graph：端到端 greeting 路径（graph.invoke）
7. build_graph：端到端 fallback 路径（graph.invoke）
8. build_graph：generate → END 边存在
"""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.workflow.builder import (
    FALLBACK_RESPONSE,
    GREETING_RESPONSE,
    _fallback_node,
    _greeting_node,
    build_graph,
)
from src.workflow.edges import route_after_classification, route_after_grade, TOOL_CALL
from src.workflow.routing import FALLBACK, GREETING, RETRIEVE


# ============================================================
# Helpers
# ============================================================

def _make_state(**overrides) -> dict:
    """构造测试用 GraphState 字典。"""
    base = {
        "messages": [],
        "question": "",
        "documents": [],
        "iteration_count": 0,
        "route_decision": "",
        "summary": "",
        "rewrite_count": 0,
        "max_rewrite_count": 1,
    }
    base.update(overrides)
    return base


def _build_graph_with_mocks():
    """用 mock 依赖构建图，返回 (compiled_graph, mock_llm)。"""
    from src.core.settings import Settings

    mock_llm = MagicMock()

    with patch("src.workflow.builder.create_retriever", return_value=MagicMock()), \
         patch("src.workflow.builder.create_llm", return_value=mock_llm):
        settings = Settings(
            deepseek_api_key="test-key",
            qwen_api_key="test-key",
        )
        graph = build_graph(settings)

    return graph, mock_llm


# ============================================================
# route_after_classification 测试
# ============================================================

class TestRouteAfterClassification:
    """条件边路由函数测试 — 验证路由决策到节点名的映射。"""

    def test_retrieve(self):
        assert route_after_classification(_make_state(route_decision=RETRIEVE)) == RETRIEVE

    def test_greeting(self):
        assert route_after_classification(_make_state(route_decision=GREETING)) == GREETING

    def test_fallback(self):
        assert route_after_classification(_make_state(route_decision=FALLBACK)) == FALLBACK

    def test_empty_defaults_to_fallback(self):
        assert route_after_classification(_make_state(route_decision="")) == FALLBACK

    def test_unknown_defaults_to_fallback(self):
        assert route_after_classification(_make_state(route_decision="unknown")) == FALLBACK

    def test_none_like_defaults_to_fallback(self):
        assert route_after_classification(_make_state(route_decision="invalid")) == FALLBACK


# ============================================================
# 终端节点函数测试
# ============================================================

class TestTerminalNodes:
    """问候/降级终端节点测试 — 验证返回正确的预设回复。"""

    def test_greeting_node_returns_greeting_response(self):
        state = _make_state()
        result = _greeting_node(state)

        assert "messages" in result
        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.content == GREETING_RESPONSE

    def test_fallback_node_returns_fallback_response(self):
        state = _make_state()
        result = _fallback_node(state)

        assert "messages" in result
        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.content == FALLBACK_RESPONSE


# ============================================================
# build_graph 测试
# ============================================================

class TestBuildGraph:
    """图构建测试 — 验证编译成功和图结构正确。"""

    def test_compiles_successfully(self):
        """图编译成功，无异常。"""
        graph, _ = _build_graph_with_mocks()
        assert graph is not None

    def test_contains_eight_nodes(self):
        """图包含 8 个业务节点（Task 2.6 新增 grade, rewrite）。"""
        graph, _ = _build_graph_with_mocks()
        node_names = {n for n in graph.nodes.keys() if not n.startswith("__")}
        expected = {
            "route", "retrieve", "grade", "rewrite",
            "memory", "generate", "greeting", "fallback",
        }
        assert node_names == expected

    def test_generate_has_end_as_successor(self):
        """generate 节点后继为 END — 通过端到端 retrieve 路径间接验证。

        DrawableGraph.edges 不包含条件边的内部目标节点，
        因此无法直接遍历边列表验证 generate → END。
        替代方案：执行 retrieve 路径，验证图能正常到达 END（不抛异常），
        间接证明 generate 后的边连接正确。
        """
        graph, mock_llm = _build_graph_with_mocks()

        with patch("src.workflow.nodes.classify_intent", return_value=RETRIEVE):
            # mock retriever 返回空文档 → generate 返回空检索回复 → END
            result = graph.invoke({
                "messages": [HumanMessage(content="什么是RAG")],
                "question": "",
                "documents": [],
                "iteration_count": 0,
                "route_decision": "",
                "summary": "",
                "rewrite_count": 0,
                "max_rewrite_count": 1,
            })

        # 图正常结束（到达 END），最后一条消息是 generate 节点的输出
        last_msg = result["messages"][-1]
        assert isinstance(last_msg, AIMessage)
        assert "iteration_count" in result

    def test_greeting_path_end_to_end(self):
        """端到端测试 greeting 路径：START → route → greeting → END。

        greeting/fallback 路径不依赖 LLM 生成（纯预设回复），
        但 route 节点需要 LLM 做意图分类。mock LLM 使其返回 "greeting"。
        """
        graph, mock_llm = _build_graph_with_mocks()

        # Mock LLM 使 StrOutputParser 解析后返回 "greeting"
        # route_node 内部链路: prompt | llm | StrOutputParser
        # StrOutputParser 调用 llm 的输出 .content
        mock_ai_msg = MagicMock()
        mock_ai_msg.content = "greeting"
        mock_llm.invoke.return_value = mock_ai_msg
        mock_llm.__or__ = MagicMock(return_value=MagicMock(
            invoke=MagicMock(return_value="greeting"),
        ))

        # 用 patch 替换 classify_intent 直接返回 "greeting"
        # 这比 mock 整个 LCEL 链更简洁可靠
        with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
            result = graph.invoke({
                "messages": [HumanMessage(content="你好")],
                "question": "",
                "documents": [],
                "iteration_count": 0,
                "route_decision": "",
                "summary": "",
                "rewrite_count": 0,
                "max_rewrite_count": 1,
            })

        # 最后一条消息应是问候回复
        last_msg = result["messages"][-1]
        assert isinstance(last_msg, AIMessage)
        assert last_msg.content == GREETING_RESPONSE

    def test_fallback_path_end_to_end(self):
        """端到端测试 fallback 路径：START → route → fallback → END。"""
        graph, mock_llm = _build_graph_with_mocks()

        with patch("src.workflow.nodes.classify_intent", return_value=FALLBACK):
            result = graph.invoke({
                "messages": [HumanMessage(content="今天天气怎么样")],
                "question": "",
                "documents": [],
                "iteration_count": 0,
                "route_decision": "",
                "summary": "",
                "rewrite_count": 0,
                "max_rewrite_count": 1,
            })

        last_msg = result["messages"][-1]
        assert isinstance(last_msg, AIMessage)
        assert last_msg.content == FALLBACK_RESPONSE


# ============================================================
# route_after_grade 测试
# ============================================================

class TestRouteAfterGrade:
    """文档评估后条件边路由测试。"""

    def test_has_docs_routes_to_memory(self):
        """有相关文档 → memory。"""
        state = _make_state(
            documents=[MagicMock()],
            rewrite_count=0,
        )
        assert route_after_grade(state) == "memory"

    def test_empty_docs_below_limit_routes_to_rewrite(self):
        """无相关文档 + 未超上限 → rewrite。"""
        state = _make_state(
            documents=[],
            rewrite_count=0,
            max_rewrite_count=2,
        )
        assert route_after_grade(state) == "rewrite"

    def test_empty_docs_at_limit_routes_to_memory(self):
        """无相关文档 + 已达上限 → memory（降级）。"""
        state = _make_state(
            documents=[],
            rewrite_count=2,
            max_rewrite_count=2,
        )
        assert route_after_grade(state) == "memory"

    def test_empty_docs_exceeded_limit_routes_to_memory(self):
        """无相关文档 + 超过上限 → memory。"""
        state = _make_state(
            documents=[],
            rewrite_count=3,
            max_rewrite_count=2,
        )
        assert route_after_grade(state) == "memory"

    def test_default_max_rewrite_count(self):
        """默认 max_rewrite_count=1 时：0 → rewrite, 1 → memory。"""
        state_0 = _make_state(documents=[], rewrite_count=0)
        assert route_after_grade(state_0) == "rewrite"

        state_1 = _make_state(documents=[], rewrite_count=1)
        assert route_after_grade(state_1) == "memory"


# ============================================================
# TOOL_CALL 常量测试
# ============================================================

class TestToolCallConstant:
    """Phase 4 预留分支标签测试。"""

    def test_tool_call_constant_exists(self):
        """TOOL_CALL 常量应等于 "tool_call"。"""
        assert TOOL_CALL == "tool_call"
