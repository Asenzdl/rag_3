"""检查点持久化测试 — 验证 create_checkpointer 工厂和多轮对话状态持久化。

测试覆盖：
1. create_checkpointer：返回 BaseCheckpointSaver 实例
2. create_checkpointer：目录自动创建
3. build_graph 向后兼容：checkpointer=None 时编译成功
4. build_graph 带 checkpointer：编译成功
5. 多轮对话状态累积：相同 thread_id，messages 逐轮增长
6. 中断恢复：关闭连接后重连，状态可恢复
7. thread_id 隔离：不同 thread_id 互不影响
8. get_state：获取当前会话完整状态快照
9. get_state_history：时间旅行调试，获取历史检查点
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from src.core.settings import Settings
from src.workflow.builder import build_graph
from src.workflow.checkpointer import create_checkpointer
from src.workflow.routing import FALLBACK, GREETING, RETRIEVE


# ============================================================
# Helpers
# ============================================================

def _make_settings(checkpoint_db_path: str = ":memory:") -> Settings:
    """创建测试用 Settings 实例。"""
    return Settings(
        deepseek_api_key="test-key",
        qwen_api_key="test-key",
        checkpoint_db_path=checkpoint_db_path,
    )


def _build_graph_with_mocks_and_checkpointer(
    settings: Settings,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """用 mock 依赖构建图，支持可选 checkpointer。"""
    mock_llm = MagicMock()

    with patch("src.workflow.builder.create_retriever", return_value=MagicMock()), \
         patch("src.workflow.builder.create_llm", return_value=mock_llm):
        graph = build_graph(settings, checkpointer=checkpointer)

    return graph, mock_llm


def _invoke_with_thread_id(graph, messages_state: dict, thread_id: str) -> dict:
    """使用指定 thread_id 调用图。"""
    config = {"configurable": {"thread_id": thread_id}}
    return graph.invoke(messages_state, config=config)


# ============================================================
# create_checkpointer 工厂函数测试
# ============================================================

class TestCreateCheckpointer:
    """检查点管理器工厂函数测试。"""

    def test_returns_base_checkpoint_saver(self):
        """create_checkpointer 返回 BaseCheckpointSaver 实例。"""
        settings = _make_settings(":memory:")
        with create_checkpointer(settings) as checkpointer:
            assert isinstance(checkpointer, BaseCheckpointSaver)

    def test_creates_directory_automatically(self):
        """create_checkpointer 自动创建数据库目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "subdir", "checkpoints.db")
            settings = _make_settings(db_path)

            with create_checkpointer(settings) as checkpointer:
                assert os.path.isdir(os.path.dirname(db_path))

    def test_setup_called_successfully(self):
        """setup() 调用成功——通过后续 invoke 验证表已创建。"""
        settings = _make_settings(":memory:")
        with create_checkpointer(settings) as checkpointer:
            # setup() 在 create_checkpointer 内部已调用
            # 验证方式：用 checkpointer 编译图并执行一次 invoke
            graph, _ = _build_graph_with_mocks_and_checkpointer(settings, checkpointer)

            with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                result = _invoke_with_thread_id(
                    graph,
                    {
                        "messages": [HumanMessage(content="你好")],
                        "question": "",
                        "documents": [],
                        "iteration_count": 0,
                        "route_decision": "",
        "summary": "",
                    },
                    "test-setup",
                )

            # 图正常执行 → setup() 成功创建了表
            assert result is not None


# ============================================================
# build_graph 向后兼容性测试
# ============================================================

class TestBuildGraphBackwardCompatibility:
    """build_graph 签名变更后的向后兼容性测试。"""

    def test_no_checkpointer_still_works(self):
        """checkpointer=None 时图编译成功并可执行。"""
        settings = _make_settings()
        graph, _ = _build_graph_with_mocks_and_checkpointer(settings, checkpointer=None)

        with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
            # 无 checkpointer 时不需 config
            result = graph.invoke({
                "messages": [HumanMessage(content="你好")],
                "question": "",
                "documents": [],
                "iteration_count": 0,
                "route_decision": "",
        "summary": "",
            })

        last_msg = result["messages"][-1]
        assert isinstance(last_msg, AIMessage)

    def test_with_checkpointer_compiles(self):
        """带 checkpointer 时图编译成功。"""
        settings = _make_settings(":memory:")
        with create_checkpointer(settings) as checkpointer:
            graph, _ = _build_graph_with_mocks_and_checkpointer(settings, checkpointer)
            assert graph is not None


# ============================================================
# 多轮对话状态累积测试（验收标准核心）
# ============================================================

class TestMultiTurnStateAccumulation:
    """多轮对话状态累积测试 — 验证相同 thread_id 下 messages 逐轮增长。"""

    def test_messages_accumulate_across_turns(self):
        """3 轮对话：messages 从 1→2→4→6 逐轮增长。"""
        settings = _make_settings(":memory:")
        with create_checkpointer(settings) as checkpointer:
            graph, _ = _build_graph_with_mocks_and_checkpointer(settings, checkpointer)
            thread_id = "accumulation-test"

            # 第 1 轮：1 HumanMessage → invoke 后 messages 包含 1 Human + 1 AI
            with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                result1 = _invoke_with_thread_id(
                    graph,
                    {
                        "messages": [HumanMessage(content="你好")],
                        "question": "",
                        "documents": [],
                        "iteration_count": 0,
                        "route_decision": "",
        "summary": "",
                    },
                    thread_id,
                )

            msg_count_1 = len(result1["messages"])
            assert msg_count_1 == 2  # 1 Human + 1 AI

            # 第 2 轮：追加新 HumanMessage，invoke 后 messages 增长
            with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                result2 = _invoke_with_thread_id(
                    graph,
                    {
                        "messages": [HumanMessage(content="你好呀")],
                        "question": "",
                        "documents": [],
                        "iteration_count": 0,
                        "route_decision": "",
        "summary": "",
                    },
                    thread_id,
                )

            msg_count_2 = len(result2["messages"])
            assert msg_count_2 == 4  # 2 Human + 2 AI

            # 第 3 轮：继续追加
            with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                result3 = _invoke_with_thread_id(
                    graph,
                    {
                        "messages": [HumanMessage(content="再问一次")],
                        "question": "",
                        "documents": [],
                        "iteration_count": 0,
                        "route_decision": "",
        "summary": "",
                    },
                    thread_id,
                )

            msg_count_3 = len(result3["messages"])
            assert msg_count_3 == 6  # 3 Human + 3 AI

    def test_get_state_returns_complete_snapshot(self):
        """graph.get_state(config) 能获取到当前会话的完整状态快照。"""
        settings = _make_settings(":memory:")
        with create_checkpointer(settings) as checkpointer:
            graph, _ = _build_graph_with_mocks_and_checkpointer(settings, checkpointer)
            thread_id = "snapshot-test"
            config = {"configurable": {"thread_id": thread_id}}

            # 执行一轮对话
            with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                _invoke_with_thread_id(
                    graph,
                    {
                        "messages": [HumanMessage(content="你好")],
                        "question": "",
                        "documents": [],
                        "iteration_count": 0,
                        "route_decision": "",
        "summary": "",
                    },
                    thread_id,
                )

            # 获取状态快照
            snapshot = graph.get_state(config)

            # StateSnapshot 包含 values、next、config 等字段
            assert snapshot.values is not None
            assert "messages" in snapshot.values
            assert len(snapshot.values["messages"]) == 2  # 1 Human + 1 AI


# ============================================================
# 中断恢复测试（验收标准核心）
# ============================================================

class TestInterruptionRecovery:
    """中断恢复测试 — 验证关闭连接后重连，状态可恢复。"""

    def test_state_persists_across_connections(self):
        """模拟中途中断：关闭连接后重新创建 checkpointer，状态可恢复。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "checkpoints.db")
            settings = _make_settings(db_path)
            thread_id = "recovery-test"

            # 第1次连接：执行 1 轮对话
            with create_checkpointer(settings) as checkpointer:
                graph, _ = _build_graph_with_mocks_and_checkpointer(settings, checkpointer)

                with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                    result1 = _invoke_with_thread_id(
                        graph,
                        {
                            "messages": [HumanMessage(content="第一轮问题")],
                            "question": "",
                            "documents": [],
                            "iteration_count": 0,
                            "route_decision": "",
        "summary": "",
                        },
                        thread_id,
                    )

                msg_count_1 = len(result1["messages"])
                assert msg_count_1 == 2

            # 连接关闭（模拟中断 / Ctrl+C 后重启）

            # 第2次连接：使用相同 thread_id 继续对话
            with create_checkpointer(settings) as checkpointer:
                graph, _ = _build_graph_with_mocks_and_checkpointer(settings, checkpointer)

                with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                    result2 = _invoke_with_thread_id(
                        graph,
                        {
                            "messages": [HumanMessage(content="第二轮问题")],
                            "question": "",
                            "documents": [],
                            "iteration_count": 0,
                            "route_decision": "",
        "summary": "",
                        },
                        thread_id,
                    )

                # 第2轮结果应包含第1轮的对话历史
                msg_count_2 = len(result2["messages"])
                assert msg_count_2 == 4  # 第1轮 2 条 + 第2轮 2 条

                # 验证第1轮的 HumanMessage 仍然存在
                human_msgs = [
                    m for m in result2["messages"] if isinstance(m, HumanMessage)
                ]
                assert len(human_msgs) == 2
                assert human_msgs[0].content == "第一轮问题"
                assert human_msgs[1].content == "第二轮问题"


# ============================================================
# thread_id 隔离测试
# ============================================================

class TestThreadIdIsolation:
    """thread_id 隔离测试 — 不同 thread_id 互不影响。"""

    def test_different_thread_ids_are_isolated(self):
        """两个不同 thread_id 各自独立，互不影响。"""
        settings = _make_settings(":memory:")
        with create_checkpointer(settings) as checkpointer:
            graph, _ = _build_graph_with_mocks_and_checkpointer(settings, checkpointer)

            # thread-1：执行 1 轮对话
            with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                result_t1 = _invoke_with_thread_id(
                    graph,
                    {
                        "messages": [HumanMessage(content="线程1的问题")],
                        "question": "",
                        "documents": [],
                        "iteration_count": 0,
                        "route_decision": "",
        "summary": "",
                    },
                    "thread-1",
                )

            # thread-2：执行 1 轮对话
            with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                result_t2 = _invoke_with_thread_id(
                    graph,
                    {
                        "messages": [HumanMessage(content="线程2的问题")],
                        "question": "",
                        "documents": [],
                        "iteration_count": 0,
                        "route_decision": "",
        "summary": "",
                    },
                    "thread-2",
                )

            # thread-1 的结果只包含 thread-1 的消息
            t1_human = [
                m for m in result_t1["messages"] if isinstance(m, HumanMessage)
            ]
            assert len(t1_human) == 1
            assert t1_human[0].content == "线程1的问题"

            # thread-2 的结果只包含 thread-2 的消息
            t2_human = [
                m for m in result_t2["messages"] if isinstance(m, HumanMessage)
            ]
            assert len(t2_human) == 1
            assert t2_human[0].content == "线程2的问题"

    def test_thread_isolation_across_turns(self):
        """不同 thread_id 在多轮后仍隔离。"""
        settings = _make_settings(":memory:")
        with create_checkpointer(settings) as checkpointer:
            graph, _ = _build_graph_with_mocks_and_checkpointer(settings, checkpointer)

            # thread-A：2 轮对话
            with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                _invoke_with_thread_id(
                    graph,
                    {
                        "messages": [HumanMessage(content="A1")],
                        "question": "",
                        "documents": [],
                        "iteration_count": 0,
                        "route_decision": "",
        "summary": "",
                    },
                    "thread-A",
                )
                _invoke_with_thread_id(
                    graph,
                    {
                        "messages": [HumanMessage(content="A2")],
                        "question": "",
                        "documents": [],
                        "iteration_count": 0,
                        "route_decision": "",
        "summary": "",
                    },
                    "thread-A",
                )

            # thread-B：1 轮对话
            with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                result_b = _invoke_with_thread_id(
                    graph,
                    {
                        "messages": [HumanMessage(content="B1")],
                        "question": "",
                        "documents": [],
                        "iteration_count": 0,
                        "route_decision": "",
        "summary": "",
                    },
                    "thread-B",
                )

            # thread-B 只有 1 轮的消息（2 条：1 Human + 1 AI），不受 thread-A 的 4 条影响
            assert len(result_b["messages"]) == 2


# ============================================================
# 时间旅行调试测试
# ============================================================

class TestTimeTravelDebugging:
    """时间旅行调试测试 — get_state_history 返回多个检查点。"""

    def test_get_state_history_returns_multiple_snapshots(self):
        """多轮对话后，get_state_history 返回多个 StateSnapshot。"""
        settings = _make_settings(":memory:")
        with create_checkpointer(settings) as checkpointer:
            graph, _ = _build_graph_with_mocks_and_checkpointer(settings, checkpointer)
            thread_id = "history-test"
            config = {"configurable": {"thread_id": thread_id}}

            # 执行 3 轮对话
            for i in range(3):
                with patch("src.workflow.nodes.classify_intent", return_value=GREETING):
                    _invoke_with_thread_id(
                        graph,
                        {
                            "messages": [HumanMessage(content=f"问题{i + 1}")],
                            "question": "",
                            "documents": [],
                            "iteration_count": 0,
                            "route_decision": "",
        "summary": "",
                        },
                        thread_id,
                    )

            # 获取历史检查点
            history = list(graph.get_state_history(config))

            # 每轮对话产生多个检查点（每个节点执行后一个），
            # 3 轮至少有 3 个检查点
            assert len(history) >= 3

            # 每个 StateSnapshot 有 values 字段
            for snapshot in history:
                assert snapshot.values is not None
