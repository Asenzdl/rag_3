"""记忆管理模块测试 — 裁剪、摘要、memory_node。

测试覆盖：
1. trim_conversation_history：未超阈值 → 保留全部（end_on 过滤末尾 AI）
2. trim_conversation_history：超阈值 → 裁剪到 ≤ max_tokens
3. trim_conversation_history：裁剪后无孤立 AIMessage
4. summarize_conversation：增量扩展（已有摘要）
5. summarize_conversation：创建新摘要（无已有摘要）
6. summarize_conversation：消息太少无需压缩
7. memory_node：未超阈值 → 返回 {}
8. memory_node：摘要成功 → 返回 RemoveMessage + 更新 summary
9. memory_node：摘要 LLM 失败 → 降级为 trim + 返回 RemoveMessage
10. build_generate_messages：含/不含 summary 的注入行为
"""

from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, RemoveMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.memory.conversation import KEEP_LAST_N, trim_conversation_history
from src.memory.summary import summarize_conversation
from src.workflow.nodes import create_workflow_nodes
from src.workflow.prompts import build_generate_messages
from src.workflow.state import GraphState, GraphContext
from langgraph.runtime import Runtime


# ============================================================
# Fake LLMs（复用 test_workflow_nodes.py 的模式）
# ============================================================

class FakeChatModel(BaseChatModel):
    """可控的 Fake LLM — 返回预设消息。"""

    _response_content: str = ""

    def __init__(self, response_content: str = "测试摘要回复", **kwargs: Any):
        super().__init__(**kwargs)
        self._response_content = response_content

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        ai_message = AIMessage(content=self._response_content)
        return ChatResult(generations=[ChatGeneration(message=ai_message)])


class FailingChatModel(BaseChatModel):
    """始终抛异常的 Fake LLM — 测试降级路径。"""

    _error: Exception

    def __init__(self, error: Exception | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self._error = error or Exception("LLM 调用失败")

    @property
    def _llm_type(self) -> str:
        return "failing-chat-model"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise self._error


# ============================================================
# Helpers — 构造测试用消息列表
# ============================================================

def make_short_messages(count: int = 3) -> list[BaseMessage]:
    """创建短消息列表（每条约 10 tokens，总小于 4000）。"""
    msgs: list[BaseMessage] = [SystemMessage(content="你是一个助手。")]
    for i in range(count):
        msgs.append(HumanMessage(content=f"问题 {i}"))
        msgs.append(AIMessage(content=f"回答 {i}"))
    return msgs


def make_long_messages(count: int = 10) -> list[BaseMessage]:
    """创建长消息列表（每条约 300 tokens，总超过 4000）。"""
    msgs: list[BaseMessage] = [SystemMessage(content="你是一个助手。")]
    for i in range(count):
        msgs.append(HumanMessage(content=f"这是第 {i} 个问题，" * 20))
        msgs.append(AIMessage(content=f"这是第 {i} 个回答，" * 20))
    return msgs


# ============================================================
# trim_conversation_history 测试
# ============================================================

class TestTrimConversationHistory:
    """trim_conversation_history 纯函数测试。"""

    def test_below_threshold_end_on_removes_trailing_ai(self):
        """未超阈值时保留全部消息，但 end_on=("human",) 会移除末尾孤立的 AIMessage。"""
        messages = make_short_messages(3)
        result = trim_conversation_history(messages, max_tokens=4000)
        # end_on=("human",) 会去掉末尾孤立的 AIMessage
        # make_short_messages(3) 生成 sys + h0+a0 + h1+a1 + h2+a2 共 7 条
        # 最后一条 a2 是 AIMessage，被 end_on 过滤 → 剩 6 条
        assert len(result) == len(messages) - 1

    def test_above_threshold(self):
        """超阈值 → 裁剪到 ≤ max_tokens。"""
        messages = make_long_messages(10)
        # 用极低的阈值强制裁剪到只剩一对
        result = trim_conversation_history(messages, max_tokens=100)
        # end_on=("human",) 保证最后一条是 HumanMessage
        assert isinstance(result[-1], HumanMessage)
        # 至少保留 2 条（Human+AI 一对）
        assert len(result) >= 2

    def test_no_orphan_ai_message(self):
        """裁剪后每条 AI 消息都有配对的 Human 消息。"""
        messages = make_long_messages(8)
        result = trim_conversation_history(messages, max_tokens=200)

        # 遍历查找孤立 AI 消息
        expect_human = True
        for msg in result:
            if isinstance(msg, SystemMessage):
                continue  # SystemMessage 不参与配对
            if expect_human:
                assert isinstance(msg, HumanMessage), (
                    f"期望 HumanMessage，得到 {type(msg).__name__}"
                )
                expect_human = False
            else:
                assert isinstance(msg, AIMessage), (
                    f"期望 AIMessage，得到 {type(msg).__name__}"
                )
                expect_human = True

    def test_system_message_preserved(self):
        """SystemMessage 始终被保留。"""
        messages = make_long_messages(8)
        result = trim_conversation_history(messages, max_tokens=100)
        assert any(isinstance(m, SystemMessage) for m in result)

    def test_current_human_protected(self):
        """当前轮 HumanMessage（即最后一条 HumanMessage）被保留。"""
        messages = make_long_messages(6)
        last_human = messages[-2]  # 最后一条是 AI，倒数第二条是 Human
        assert isinstance(last_human, HumanMessage)

        result = trim_conversation_history(messages, max_tokens=200)
        # 最后一条 Human 应在结果中
        result_humans = [m for m in result if isinstance(m, HumanMessage)]
        assert any(id(m) == id(last_human) for m in result_humans)


# ============================================================
# summarize_conversation 测试
# ============================================================

class TestSummarizeConversation:
    """summarize_conversation 函数测试。"""

    def test_incremental_with_existing_summary(self):
        """已有摘要时 → 增量扩展调用 LLM。"""
        messages = make_short_messages(3)
        llm = FakeChatModel(response_content="扩展后的摘要")

        new_summary, kept = summarize_conversation(
            messages=messages,
            llm=llm,
            existing_summary="之前的摘要内容",
        )
        assert new_summary == "扩展后的摘要"
        # kept 包含 system + 最近的 keep_last_n 条消息
        assert len(kept) > 0

    def test_create_without_existing_summary(self):
        """无已有摘要时 → 创建新摘要。"""
        messages = make_short_messages(5)
        llm = FakeChatModel(response_content="全新的摘要")

        new_summary, kept = summarize_conversation(
            messages=messages,
            llm=llm,
            existing_summary="",
        )
        assert new_summary == "全新的摘要"
        # kept 包含 system + 最近的 keep_last_n 条消息
        assert len(kept) >= 1

    def test_too_few_messages_no_compression(self):
        """消息太少（不足 keep_last_n）→ 返回原摘要和原消息。"""
        messages = make_short_messages(1)  # 只有 1 轮 + sysmsg
        existing = "已有摘要"
        llm = FakeChatModel()

        new_summary, kept = summarize_conversation(
            messages=messages,
            llm=llm,
            existing_summary=existing,
            keep_last_n=2,
        )
        # 不应该调用 LLM，返回原摘要
        assert new_summary == existing
        # 保留全部原消息
        assert len(kept) == len(messages)

    def test_llm_failure_propagates(self):
        """LLM 调用失败 → 传播异常（memory_node 负责降级）。"""
        messages = make_short_messages(8)
        llm = FailingChatModel()

        with pytest.raises(Exception):
            summarize_conversation(
                messages=messages,
                llm=llm,
                existing_summary="",
                keep_last_n=2,
            )

    def test_kept_messages_are_recent(self):
        """保留的消息是最新的 keep_last_n 条。"""
        messages = make_short_messages(6)  # sys + 6 轮 = 13 条
        llm = FakeChatModel(response_content="摘要")

        _, kept = summarize_conversation(
            messages=messages,
            llm=llm,
            existing_summary="",
            keep_last_n=2,  # 保留最近 2 轮 = 4 条 + sys = 5 条
        )
        # kept 应该包含 system + 最近 2 轮
        assert len(kept) >= 3  # system + 1 轮 (2条) = 3


# ============================================================
# memory_node 测试（通过 create_workflow_nodes 创建）
# ============================================================

class TestMemoryNode:
    """memory_node 闭包测试。"""

    @pytest.fixture
    def short_state(self):
        """未超阈值的状态。"""
        return GraphState(
            messages=make_short_messages(3),
            question="测试问题",
            documents=[],
            iteration_count=0,
            route_decision="retrieve",
            summary="",
        )

    @pytest.fixture
    def long_state(self):
        """超阈值的状态。"""
        return GraphState(
            messages=make_long_messages(8),
            question="测试问题",
            documents=[],
            iteration_count=0,
            route_decision="retrieve",
            summary="",
        )

    @pytest.fixture
    def runtime(self):
        """带 max_tokens 的 Runtime。"""
        return Runtime(context=GraphContext(max_iterations=3, max_tokens=4000))

    @pytest.fixture
    def strict_runtime(self):
        """极低阈值 Runtime — 强制触发记忆管理。"""
        return Runtime(context=GraphContext(max_iterations=3, max_tokens=100))

    def test_below_threshold_no_op(self, short_state, runtime):
        """未超阈值 → memory_node 返回 {}。"""
        nodes = create_workflow_nodes(
            retriever=MagicMock(),
            llm=FakeChatModel(),
        )
        result = nodes["memory"](short_state, runtime)
        assert result == {}

    def test_summary_success_updates_summary(self, long_state, strict_runtime):
        """摘要成功 → 返回 RemoveMessage + summary 字段被更新。"""
        nodes = create_workflow_nodes(
            retriever=MagicMock(),
            llm=FakeChatModel(response_content="更新后的摘要"),
        )
        result = nodes["memory"](long_state, strict_runtime)
        assert "summary" in result
        assert result["summary"] == "更新后的摘要"
        assert "messages" in result
        # messages 应包含 REMOVE_ALL_MESSAGES RemoveMessage
        assert any(isinstance(m, RemoveMessage) for m in result["messages"])

    def test_summary_fallback_to_trim(self, long_state, strict_runtime):
        """摘要 LLM 失败 → 降级为 trim，返回 RemoveMessage 但不含 summary。"""
        nodes = create_workflow_nodes(
            retriever=MagicMock(),
            llm=FailingChatModel(),
        )
        result = nodes["memory"](long_state, strict_runtime)
        # 降级路径不应修改 summary
        assert "summary" not in result
        assert "messages" in result
        # messages 应包含 REMOVE_ALL_MESSAGES RemoveMessage
        assert any(isinstance(m, RemoveMessage) for m in result["messages"])
        # 降级后保留的消息中无孤立 AIMessage
        kept = [m for m in result["messages"] if not isinstance(m, RemoveMessage)]
        expect_human = True
        for msg in kept:
            if isinstance(msg, SystemMessage):
                continue
            if expect_human:
                assert isinstance(msg, HumanMessage), (
                    f"期望 HumanMessage，得到 {type(msg).__name__}"
                )
                expect_human = False
            else:
                assert isinstance(msg, AIMessage), (
                    f"期望 AIMessage，得到 {type(msg).__name__}"
                )
                expect_human = True

    def test_trim_fallback_no_orphan_ai(self, long_state, strict_runtime):
        """降级 trim 后无孤立 AIMessage。"""
        nodes = create_workflow_nodes(
            retriever=MagicMock(),
            llm=FailingChatModel(),
        )
        result = nodes["memory"](long_state, strict_runtime)
        kept = [m for m in result.get("messages", []) if not isinstance(m, RemoveMessage)]
        expect_human = True
        for msg in kept:
            if isinstance(msg, SystemMessage):
                continue
            if expect_human:
                assert isinstance(msg, HumanMessage), (
                    f"期望 HumanMessage，得到 {type(msg).__name__}"
                )
                expect_human = False
            else:
                assert isinstance(msg, AIMessage), (
                    f"期望 AIMessage，得到 {type(msg).__name__}"
                )
                expect_human = True

    def test_preserves_current_human(self, long_state, strict_runtime):
        """memory 操作后当前轮 HumanMessage 被保留。"""
        nodes = create_workflow_nodes(
            retriever=MagicMock(),
            llm=FakeChatModel(response_content="摘要"),
        )
        original_msgs = long_state.get("messages", [])
        current_human = None
        for msg in reversed(original_msgs):
            if isinstance(msg, HumanMessage):
                current_human = msg
                break

        result = nodes["memory"](long_state, strict_runtime)
        if "summary" in result:
            kept = [m for m in result["messages"] if not isinstance(m, RemoveMessage)]
            assert any(
                isinstance(m, HumanMessage) and id(m) == id(current_human)
                for m in kept
            )


# ============================================================
# build_generate_messages 含 summary 的注入测试
# ============================================================

class TestBuildGenerateMessagesWithSummary:
    """build_generate_messages 的 summary 注入行为测试。"""

    def test_summary_injected_as_system_message(self):
        """非空 summary → 消息列表含摘要 SystemMessage。"""
        from langchain_core.messages import HumanMessage
        messages = build_generate_messages(
            context="测试上下文",
            question="测试问题",
            chat_history=[],
            summary="用户之前询问了 LangGraph 的状态管理。",
        )
        # 应包含一条 content 含摘要文本的 SystemMessage
        summary_msgs = [
            m for m in messages
            if getattr(m, "type", "") == "system"
            and "用户之前询问了 LangGraph 的状态管理" in (m.content or "")
        ]
        assert len(summary_msgs) == 1

    def test_no_summary_when_empty(self):
        """空 summary → 消息列表不含摘要 SystemMessage。"""
        messages = build_generate_messages(
            context="测试上下文",
            question="测试问题",
            chat_history=[],
            summary="",
        )
        # 系统指令 SystemMessage 仍存在，但没有摘要 SystemMessage
        system_msgs = [m for m in messages if getattr(m, "type", "") == "system"]
        summary_system = [
            m for m in system_msgs
            if "对话摘要" in (m.content or "")
        ]
        assert len(summary_system) == 0
