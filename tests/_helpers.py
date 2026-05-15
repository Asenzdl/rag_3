"""共享测试工具 — FakeChatModel、图构建工厂、Settings 工厂。

为什么独立为模块而非放在 conftest.py 中：
    conftest.py 的 pytest 约定是 fixture + hooks 声明，不是类定义场所。
    FakeChatModel 有 60 行完整 BaseChatModel 子类实现，放在 conftest.py
    会导致文件膨胀且语义混乱。测试文件可 from tests._helpers import ... 显式导入。
"""

from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.base import BaseCheckpointSaver

from src.core.settings import Settings
from src.workflow.builder import build_graph


# ============================================================
# FakeChatModel — 替代 MagicMock，满足 LCEL Runnable 协议
# ============================================================


class FakeChatModel(BaseChatModel):
    """可控的 Fake LLM — 返回预设消息，支持 LCEL 链（prompt | llm | parser）。

    为什么用 FakeChatModel 而非 MagicMock（反直觉辩护）：
        LCEL 的 | 操作符对操作数做 coerce_to_runnable() 校验，
        MagicMock 不满足 Runnable 协议会被包装为 RunnableLambda，
        导致 mock()（而非 mock.invoke()）被调用，返回值类型错误。
        FakeChatModel 继承 BaseChatModel，| 操作正常工作，
        同时通过 _response_content 属性控制返回内容。

    限制：
        不支持 with_structured_output()（会触发真实网络调用）。
        grade 节点需用 MagicMock(spec=BaseChatModel) 替代。
    """

    _response_content: str = ""

    def __init__(self, response_content: str = "测试回复", **kwargs: Any):
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
        ai_message.usage_metadata = {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }
        return ChatResult(generations=[ChatGeneration(message=ai_message)])


class FailingChatModel(BaseChatModel):
    """始终抛异常的 Fake LLM — 用于测试异常路径。"""

    _error: Exception

    def __init__(self, error: Exception, **kwargs: Any):
        super().__init__(**kwargs)
        self._error = error

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
# 图构建工厂
# ============================================================


def build_graph_with_mocks(
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> tuple:
    """用 mock 依赖构建图，返回 (compiled_graph, mock_llm)。

    为什么统一 builder 和 checkpointer 两个版本：
        原来的 _build_graph_with_mocks（builder 测试，不接受 checkpointer）
        和 _build_graph_with_mocks_and_checkpointer（checkpointer 测试，接受
        settings + checkpointer 参数）逻辑相同，仅签名不同。
        统一为 settings=None 时自动创建默认 Settings，
        checkpointer=None 时走无持久化路径。
    """
    if settings is None:
        settings = make_settings(checkpoint_db_path="")

    mock_llm = MagicMock()

    with (
        patch("src.workflow.builder.create_retriever", return_value=MagicMock()),
        patch("src.workflow.builder.create_llm", return_value=mock_llm),
    ):
        graph = build_graph(settings, checkpointer=checkpointer)

    return graph, mock_llm


def make_settings(checkpoint_db_path: str = ":memory:") -> Settings:
    """创建测试用 Settings 实例。"""
    return Settings(
        deepseek_api_key="test-key",
        qwen_api_key="test-key",
        checkpoint_db_path=checkpoint_db_path,
    )


def invoke_with_thread_id(graph, messages_state: dict, thread_id: str) -> dict:
    """使用指定 thread_id 调用图。"""
    config = {"configurable": {"thread_id": thread_id}}
    return graph.invoke(messages_state, config=config)
