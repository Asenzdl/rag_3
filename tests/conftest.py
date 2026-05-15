"""共享测试 fixtures — 从 _helpers 导入类，声明 pytest fixture。

职责分离：
    _helpers.py — 类定义和工具函数（可被测试文件显式 import）
    conftest.py — fixture 声明（pytest 自动发现，无需显式 import）
"""

import pytest
from langchain_core.documents import Document
from unittest.mock import MagicMock

from tests._helpers import (
    FakeChatModel,
    FailingChatModel,
    build_graph_with_mocks,
    invoke_with_thread_id,
    make_settings,
)
from src.workflow.state import GraphContext

from langgraph.runtime import Runtime


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_retriever():
    """返回 2 个 Document 的 mock retriever。"""
    retriever = MagicMock()
    retriever.invoke.return_value = [
        Document(
            page_content="LangGraph 是一个用于构建状态化、多步骤 AI 应用的框架。",
            metadata={"source": "https://langchain-ai.github.io/langgraph/"},
        ),
        Document(
            page_content="LangGraph 支持 checkpoint 持久化和流式输出。",
            metadata={"source": "https://langchain-ai.github.io/langgraph/concepts/"},
        ),
    ]
    return retriever


@pytest.fixture
def default_runtime():
    """默认 Runtime[GraphContext] 实例。"""
    return Runtime(context=GraphContext(max_iterations=3))
