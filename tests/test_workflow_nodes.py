"""工作流节点函数测试 — 路由、检索、生成。

测试覆盖：
1. classify_intent：问候 → greeting；知识库问题 → retrieve；无关问题 → fallback
2. classify_intent：LLM 调用失败 → 默认 retrieve
3. classify_intent：LLM 输出无法识别 → 默认 retrieve
4. route_node：正常分类 + 提取 question
5. route_node：messages 中无 HumanMessage → question=""
6. retrieve_node：正常检索 → documents 非空
7. retrieve_node：RetrievalError → documents=[]
8. retrieve_node：未预期异常 → documents=[]
9. generate_node：正常生成 → messages 含 AIMessage + iteration_count 递增
10. generate_node：空文档 → 返回空检索预设回复 + iteration_count 递增
11. generate_node：LLM 调用异常 → 返回错误回复 + iteration_count 递增
12. generate_node：未预期异常 → 返回错误回复 + iteration_count 递增
"""

from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.prompts import ChatPromptTemplate

from src.retriever.base_retriever import RetrievalError
from src.workflow.nodes import (
    EMPTY_RETRIEVAL_RESPONSE,
    GENERATION_ERROR_RESPONSE,
    create_workflow_nodes,
)
from src.workflow.routing import (
    FALLBACK,
    GREETING,
    RETRIEVE,
    VALID_ROUTE_DECISIONS,
    classify_intent,
    create_route_prompt,
)
from src.workflow.state import GraphState


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
# Fixtures
# ============================================================

@pytest.fixture
def mock_retriever():
    """Mock RetrieverProtocol — invoke 返回预设文档列表。"""
    retriever = MagicMock()
    retriever.invoke.return_value = [
        Document(
            page_content="LangGraph is a framework for building stateful applications.",
            metadata={"source": "https://example.com/langgraph"},
        ),
        Document(
            page_content="StateGraph is the core class.",
            metadata={"source": "https://example.com/stateggraph"},
        ),
    ]
    return retriever


@pytest.fixture
def mock_prompt():
    """简单 ChatPromptTemplate。"""
    return ChatPromptTemplate.from_messages([
        ("system", "你是助手"),
        ("human", "{context}\n\n问题：{question}"),
    ])


@pytest.fixture
def initial_state():
    """标准初始状态 — 包含一条用户消息。"""
    return GraphState(
        messages=[HumanMessage(content="LangGraph 是什么？")],
        question="",
        documents=[],
        iteration_count=0,
        route_decision="",
    )


@pytest.fixture
def state_with_documents():
    """含文档的状态 — 模拟检索后状态。"""
    docs = [
        Document(
            page_content="LangGraph is a framework.",
            metadata={"source": "https://example.com/1"},
        ),
    ]
    return GraphState(
        messages=[HumanMessage(content="LangGraph 是什么？")],
        question="LangGraph 是什么？",
        documents=docs,
        iteration_count=0,
        route_decision="retrieve",
    )


# ============================================================
# routing.py 测试
# ============================================================

class TestRouteConstants:
    """路由标签常量测试。"""

    def test_valid_route_decisions_contains_all(self):
        """VALID_ROUTE_DECISIONS 应包含所有路由标签。"""
        assert RETRIEVE in VALID_ROUTE_DECISIONS
        assert GREETING in VALID_ROUTE_DECISIONS
        assert FALLBACK in VALID_ROUTE_DECISIONS
        assert len(VALID_ROUTE_DECISIONS) == 3

    def test_route_values_match_state_field(self):
        """路由标签值应与 GraphState.route_decision 的可能值对齐。"""
        assert RETRIEVE == "retrieve"
        assert GREETING == "greeting"
        assert FALLBACK == "fallback"


class TestCreateRoutePrompt:
    """路由 Prompt 模板创建测试。"""

    def test_create_route_prompt_returns_template(self):
        """create_route_prompt 应返回 ChatPromptTemplate 实例。"""
        prompt = create_route_prompt()
        assert isinstance(prompt, ChatPromptTemplate)

    def test_route_prompt_has_question_variable(self):
        """路由 Prompt 应包含 question 输入变量。"""
        prompt = create_route_prompt()
        assert "question" in prompt.input_variables


class TestClassifyIntent:
    """意图分类函数测试。"""

    def test_greeting_classification(self):
        """问候问题 → greeting。"""
        llm = FakeChatModel(response_content="greeting")
        result = classify_intent("你好", llm)
        assert result == GREETING

    def test_retrieve_classification(self):
        """知识库问题 → retrieve。"""
        llm = FakeChatModel(response_content="retrieve")
        result = classify_intent("LangGraph 是什么？", llm)
        assert result == RETRIEVE

    def test_fallback_classification(self):
        """无关问题 → fallback。"""
        llm = FakeChatModel(response_content="fallback")
        result = classify_intent("今天天气怎么样", llm)
        assert result == FALLBACK

    def test_llm_output_with_extra_text(self):
        """LLM 输出含多余文本 → 子串匹配仍能识别。"""
        llm = FakeChatModel(response_content="The intent is: retrieve")
        result = classify_intent("LangGraph 是什么？", llm)
        assert result == RETRIEVE

    def test_llm_output_with_whitespace(self):
        """LLM 输出含空白字符 → strip 后正常匹配。"""
        llm = FakeChatModel(response_content="  greeting  \n")
        result = classify_intent("你好", llm)
        assert result == GREETING

    def test_llm_output_unrecognized(self):
        """LLM 输出无法识别 → 默认 retrieve。"""
        llm = FakeChatModel(response_content="unknown_label")
        result = classify_intent("测试问题", llm)
        assert result == RETRIEVE

    def test_llm_call_failure(self):
        """LLM 调用失败 → 默认 retrieve。"""
        llm = FailingChatModel(error=RuntimeError("API timeout"))
        result = classify_intent("测试问题", llm)
        assert result == RETRIEVE

    def test_case_insensitive_matching(self):
        """LLM 输出大写 → 转小写后匹配。"""
        llm = FakeChatModel(response_content="RETRIEVE")
        result = classify_intent("LangGraph 是什么？", llm)
        assert result == RETRIEVE


# ============================================================
# nodes.py 测试
# ============================================================

class TestCreateWorkflowNodes:
    """工作流节点工厂函数测试。"""

    def test_factory_returns_three_nodes(self, mock_retriever, mock_prompt):
        """工厂函数应返回包含三个节点函数的字典。"""
        llm = FakeChatModel(response_content="retrieve")
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        assert "route" in nodes
        assert "retrieve" in nodes
        assert "generate" in nodes
        assert len(nodes) == 3

    def test_node_functions_are_callable(self, mock_retriever, mock_prompt):
        """每个节点函数都应可调用。"""
        llm = FakeChatModel()
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        for name, func in nodes.items():
            assert callable(func), f"节点 {name} 不是可调用对象"


class TestRouteNode:
    """路由节点测试。"""

    def test_route_node_returns_question_and_decision(
        self, mock_retriever, mock_prompt, initial_state,
    ):
        """路由节点应返回 question + route_decision。"""
        llm = FakeChatModel(response_content="retrieve")
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        result = nodes["route"](initial_state)

        assert "question" in result
        assert "route_decision" in result
        assert result["question"] == "LangGraph 是什么？"
        assert result["route_decision"] == RETRIEVE

    def test_route_node_greeting(
        self, mock_retriever, mock_prompt,
    ):
        """问候问题 → route_decision=greeting。"""
        llm = FakeChatModel(response_content="greeting")
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        state = GraphState(
            messages=[HumanMessage(content="你好")],
            question="",
            documents=[],
            iteration_count=0,
            route_decision="",
        )
        result = nodes["route"](state)

        assert result["route_decision"] == GREETING
        assert result["question"] == "你好"

    def test_route_node_fallback(
        self, mock_retriever, mock_prompt,
    ):
        """无关问题 → route_decision=fallback。"""
        llm = FakeChatModel(response_content="fallback")
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        state = GraphState(
            messages=[HumanMessage(content="今天天气怎么样")],
            question="",
            documents=[],
            iteration_count=0,
            route_decision="",
        )
        result = nodes["route"](state)

        assert result["route_decision"] == FALLBACK

    def test_route_node_no_human_message(
        self, mock_retriever, mock_prompt,
    ):
        """messages 中无 HumanMessage → question=""。"""
        llm = FakeChatModel(response_content="fallback")
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        state = GraphState(
            messages=[AIMessage(content="系统消息")],
            question="",
            documents=[],
            iteration_count=0,
            route_decision="",
        )
        result = nodes["route"](state)

        assert result["question"] == ""

    def test_route_node_extracts_latest_human_message(
        self, mock_retriever, mock_prompt,
    ):
        """多轮对话 → 提取最后一条 HumanMessage。"""
        llm = FakeChatModel(response_content="retrieve")
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        state = GraphState(
            messages=[
                HumanMessage(content="第一个问题"),
                AIMessage(content="第一个回答"),
                HumanMessage(content="第二个问题"),
            ],
            question="",
            documents=[],
            iteration_count=0,
            route_decision="",
        )
        result = nodes["route"](state)

        assert result["question"] == "第二个问题"


class TestRetrieveNode:
    """检索节点测试。"""

    def test_retrieve_node_normal(
        self, mock_retriever, mock_prompt, state_with_documents,
    ):
        """正常检索 → documents 非空。"""
        llm = FakeChatModel()
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        result = nodes["retrieve"](state_with_documents)

        assert "documents" in result
        assert len(result["documents"]) == 2
        assert result["documents"][0].metadata.get("source") == "https://example.com/langgraph"

    def test_retrieve_node_returns_documents_only(
        self, mock_retriever, mock_prompt, state_with_documents,
    ):
        """检索节点只返回 documents，不修改其他字段。"""
        llm = FakeChatModel()
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        result = nodes["retrieve"](state_with_documents)

        assert set(result.keys()) == {"documents"}

    def test_retrieve_node_retrieval_error(self, mock_prompt):
        """RetrievalError → documents=[]。"""
        mock_retriever = MagicMock()
        mock_retriever.invoke.side_effect = RetrievalError("连接超时")

        llm = FakeChatModel()
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        state = GraphState(
            messages=[HumanMessage(content="测试")],
            question="测试问题",
            documents=[],
            iteration_count=0,
            route_decision="retrieve",
        )
        result = nodes["retrieve"](state)

        assert result["documents"] == []

    def test_retrieve_node_unexpected_exception(self, mock_prompt):
        """未预期异常 → documents=[]。"""
        mock_retriever = MagicMock()
        mock_retriever.invoke.side_effect = RuntimeError("未知错误")

        llm = FakeChatModel()
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        state = GraphState(
            messages=[HumanMessage(content="测试")],
            question="测试问题",
            documents=[],
            iteration_count=0,
            route_decision="retrieve",
        )
        result = nodes["retrieve"](state)

        assert result["documents"] == []

    def test_retrieve_node_uses_question(
        self, mock_retriever, mock_prompt,
    ):
        """检索节点应使用 state["question"] 调用 retriever。"""
        llm = FakeChatModel()
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        state = GraphState(
            messages=[HumanMessage(content="测试")],
            question="LangGraph 是什么？",
            documents=[],
            iteration_count=0,
            route_decision="retrieve",
        )
        nodes["retrieve"](state)

        mock_retriever.invoke.assert_called_once_with("LangGraph 是什么？")


class TestGenerateNode:
    """生成节点测试。"""

    def test_generate_node_normal(
        self, mock_retriever, mock_prompt, state_with_documents,
    ):
        """正常生成 → messages 含 AIMessage + iteration_count 递增。"""
        llm = FakeChatModel(response_content="LangGraph 是一个框架")
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        result = nodes["generate"](state_with_documents)

        assert "messages" in result
        assert "iteration_count" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert result["messages"][0].content == "LangGraph 是一个框架"
        assert result["iteration_count"] == 1

    def test_generate_node_empty_documents(
        self, mock_retriever, mock_prompt,
    ):
        """空文档 → 返回空检索预设回复 + iteration_count 递增。"""
        llm = FakeChatModel()
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        state = GraphState(
            messages=[HumanMessage(content="测试")],
            question="测试问题",
            documents=[],
            iteration_count=0,
            route_decision="retrieve",
        )
        result = nodes["generate"](state)

        assert result["messages"][0].content == EMPTY_RETRIEVAL_RESPONSE
        assert result["iteration_count"] == 1

    def test_generate_node_llm_failure(
        self, mock_retriever, mock_prompt, state_with_documents,
    ):
        """LLM 调用异常 → 返回错误回复 + iteration_count 递增。"""
        llm = FailingChatModel(error=RuntimeError("API timeout"))
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        result = nodes["generate"](state_with_documents)

        assert result["messages"][0].content == GENERATION_ERROR_RESPONSE
        assert result["iteration_count"] == 1

    def test_generate_node_iteration_count_increments(
        self, mock_retriever, mock_prompt, state_with_documents,
    ):
        """每次调用 generate_node，iteration_count 应 +1。"""
        llm = FakeChatModel(response_content="回答")
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)

        # 第一次调用
        result1 = nodes["generate"](state_with_documents)
        assert result1["iteration_count"] == 1

        # 模拟第二次调用（状态中 iteration_count 已更新为 1）
        state_with_documents["iteration_count"] = 1
        result2 = nodes["generate"](state_with_documents)
        assert result2["iteration_count"] == 2

    def test_generate_node_returns_messages_and_count_only(
        self, mock_retriever, mock_prompt, state_with_documents,
    ):
        """生成节点只返回 messages 和 iteration_count。"""
        llm = FakeChatModel(response_content="回答")
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)
        result = nodes["generate"](state_with_documents)

        assert set(result.keys()) == {"messages", "iteration_count"}


# ============================================================
# 集成级：节点协作测试
# ============================================================

class TestNodeCollaboration:
    """节点协作测试 — 验证 route → retrieve → generate 的数据流。"""

    def test_full_pipeline_route_then_retrieve(
        self, mock_retriever, mock_prompt,
    ):
        """route_node 输出 → retrieve_node 输入 的数据流正确。"""
        llm = FakeChatModel(response_content="retrieve")
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)

        # 初始状态
        initial = GraphState(
            messages=[HumanMessage(content="LangGraph 是什么？")],
            question="",
            documents=[],
            iteration_count=0,
            route_decision="",
        )

        # 第1步：路由
        route_result = nodes["route"](initial)
        assert route_result["question"] == "LangGraph 是什么？"
        assert route_result["route_decision"] == RETRIEVE

        # 第2步：模拟状态更新后传入检索节点
        state_after_route = {**initial, **route_result}
        retrieve_result = nodes["retrieve"](state_after_route)
        assert len(retrieve_result["documents"]) == 2

    def test_full_pipeline_all_three_nodes(
        self, mock_retriever, mock_prompt,
    ):
        """route → retrieve → generate 完整流程。"""
        llm = FakeChatModel(response_content="LangGraph 是一个框架")
        nodes = create_workflow_nodes(mock_retriever, llm, mock_prompt)

        initial = GraphState(
            messages=[HumanMessage(content="LangGraph 是什么？")],
            question="",
            documents=[],
            iteration_count=0,
            route_decision="",
        )

        # route
        route_result = nodes["route"](initial)
        # retrieve
        state_after_route = {**initial, **route_result}
        retrieve_result = nodes["retrieve"](state_after_route)
        # generate
        state_after_retrieve = {**state_after_route, **retrieve_result}
        generate_result = nodes["generate"](state_after_retrieve)

        assert generate_result["iteration_count"] == 1
        assert len(generate_result["messages"]) == 1
        assert isinstance(generate_result["messages"][0], AIMessage)
        assert generate_result["messages"][0].content == "LangGraph 是一个框架"
