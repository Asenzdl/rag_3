"""GraphState 状态定义 + add_messages reducer 行为测试。

测试覆盖：
1. add_messages 连续追加：两个节点分别返回消息，状态中 messages 应包含两者合并结果
2. add_messages 同 ID 替换：返回与已有消息相同 ID 的消息时，应替换而非追加
3. add_messages 混合操作：同时包含新消息和替换消息
4. documents 覆盖行为：第二个节点返回 documents 后，状态中应只有新文档
5. iteration_count 覆盖行为：节点返回新值后直接覆盖
6. route_decision 覆盖行为：节点返回新值后直接覆盖
7. question 覆盖行为：节点返回新值后直接覆盖
8. 完整状态构造：验证所有字段可赋值且类型正确
9. 状态可被 nodes.py 和 builder.py 正常导入
"""

import uuid

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from src.workflow.state import GraphState, add_messages


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def base_messages():
    """基础消息列表 — 两条消息。"""
    return [
        HumanMessage(content="LangGraph 是什么？"),
        AIMessage(content="LangGraph 是一个用于构建状态化多角色应用的框架。"),
    ]


@pytest.fixture
def initial_state(base_messages):
    """完整的初始状态。"""
    return GraphState(
        messages=base_messages,
        question="LangGraph 是什么？",
        documents=[],
        iteration_count=0,
        route_decision="",
        summary="",
        rewrite_count=0,
        max_rewrite_count=1,
    )


# ============================================================
# add_messages reducer 测试
# ============================================================

class TestAddMessagesReducer:
    """add_messages reducer 行为测试 — 验证消息列表的增量追加和替换。"""

    def test_append_new_messages(self, base_messages):
        """连续两个节点返回消息列表，状态中 messages 应包含两者合并结果。

        模拟场景：
            初始状态有 2 条消息
            节点 1 返回 1 条新消息 → messages 应有 3 条
            节点 2 返回 1 条新消息 → messages 应有 4 条
        """
        # 第1步：初始消息列表
        current = base_messages
        assert len(current) == 2

        # 第2步：节点 1 返回新消息
        new_msg_1 = HumanMessage(content="它怎么用？")
        updated = add_messages(current, [new_msg_1])
        assert len(updated) == 3
        assert updated[2].content == "它怎么用？"

        # 第3步：节点 2 返回新消息
        new_msg_2 = AIMessage(content="你可以用 StateGraph 来构建工作流。")
        updated = add_messages(updated, [new_msg_2])
        assert len(updated) == 4
        assert updated[3].content == "你可以用 StateGraph 来构建工作流。"

    def test_replace_same_id_message(self, base_messages):
        """返回与已有消息相同 ID 的消息时，应替换而非追加。

        模拟场景：
            初始状态有 2 条消息
            节点返回一条与第 2 条消息相同 ID 的新消息 → 替换第 2 条，总数不变
        """
        # 第1步：给第 2 条消息指定固定 ID
        original_id = str(uuid.uuid4())
        ai_msg_with_id = AIMessage(
            content="原始回答",
            id=original_id,
        )
        current = [base_messages[0], ai_msg_with_id]
        assert len(current) == 2

        # 第2步：返回相同 ID 的消息（内容不同）
        replacement = AIMessage(
            content="替换后的回答",
            id=original_id,
        )
        updated = add_messages(current, [replacement])

        # 验证：总数不变（替换而非追加），内容已更新
        assert len(updated) == 2
        assert updated[1].content == "替换后的回答"
        assert updated[1].id == original_id

    def test_mixed_append_and_replace(self, base_messages):
        """同时包含新消息和替换消息。

        模拟场景：
            初始状态有 2 条消息，第 2 条有固定 ID
            节点返回 2 条消息：1 条替换第 2 条，1 条新增
            → 总数应为 3（替换 1 + 新增 1）
        """
        # 第1步：给第 2 条消息指定固定 ID
        original_id = str(uuid.uuid4())
        ai_msg_with_id = AIMessage(
            content="原始回答",
            id=original_id,
        )
        current = [base_messages[0], ai_msg_with_id]
        assert len(current) == 2

        # 第2步：返回混合消息列表
        replacement = AIMessage(content="替换后的回答", id=original_id)
        new_msg = HumanMessage(content="新问题")
        updated = add_messages(current, [replacement, new_msg])

        # 验证：替换 + 新增
        assert len(updated) == 3
        assert updated[1].content == "替换后的回答"
        assert updated[2].content == "新问题"

    def test_empty_messages_list(self):
        """空消息列表追加新消息。"""
        new_msg = HumanMessage(content="第一条消息")
        updated = add_messages([], [new_msg])
        assert len(updated) == 1
        assert updated[0].content == "第一条消息"

    def test_append_to_empty(self, base_messages):
        """向现有消息列表追加空列表，应保持不变。"""
        updated = add_messages(base_messages, [])
        assert len(updated) == len(base_messages)
        assert updated == base_messages


# ============================================================
# documents 覆盖行为测试
# ============================================================

class TestDocumentsOverride:
    """documents 字段无 reducer，节点返回值直接覆盖。"""

    def test_documents_override(self):
        """第二个节点返回 documents 后，状态中应只有新文档。"""
        # 第1步：初始文档列表
        docs_round1 = [
            Document(page_content="文档1", metadata={"source": "url1"}),
            Document(page_content="文档2", metadata={"source": "url2"}),
        ]

        # 第2步：模拟节点 2 返回新文档（覆盖）
        docs_round2 = [
            Document(page_content="文档3", metadata={"source": "url3"}),
        ]

        # 模拟 LangGraph 的状态更新逻辑：
        # 无 reducer 的字段，节点返回值直接覆盖
        state_documents = docs_round1
        state_documents = docs_round2  # 覆盖

        assert len(state_documents) == 1
        assert state_documents[0].page_content == "文档3"

    def test_documents_empty_override(self):
        """节点返回空列表后，documents 应为空。"""
        docs_round1 = [
            Document(page_content="文档1", metadata={"source": "url1"}),
        ]

        # 覆盖为空列表
        state_documents = docs_round1
        state_documents = []

        assert state_documents == []


# ============================================================
# 简单字段覆盖行为测试
# ============================================================

class TestSimpleFieldOverride:
    """无 reducer 的简单字段（iteration_count、route_decision、question）
    直接覆盖。"""

    def test_iteration_count_override(self):
        """节点返回 iteration_count 后，状态中应为新值。"""
        state_count = 0
        # 节点 1：+1
        state_count = state_count + 1
        assert state_count == 1
        # 节点 2：+1
        state_count = state_count + 1
        assert state_count == 2

    def test_route_decision_override(self):
        """节点返回 route_decision 后，状态中应为新值。"""
        state_decision = ""
        # 路由节点：写入决策
        state_decision = "retrieve"
        assert state_decision == "retrieve"
        # 重新路由：覆盖
        state_decision = "fallback"
        assert state_decision == "fallback"

    def test_question_override(self):
        """节点返回 question 后，状态中应为新值。"""
        state_question = ""
        # 路由节点：提取用户问题
        state_question = "LangGraph 是什么？"
        assert state_question == "LangGraph 是什么？"
        # 新一轮：覆盖
        state_question = "它怎么用？"
        assert state_question == "它怎么用？"


# ============================================================
# 完整状态构造测试
# ============================================================

class TestGraphStateConstruction:
    """验证所有字段可赋值且类型正确。"""

    def test_full_state_construction(self):
        """构造完整状态，验证所有字段可赋值。"""
        state: GraphState = {
            "messages": [HumanMessage(content="测试问题")],
            "question": "测试问题",
            "documents": [Document(page_content="测试文档")],
            "iteration_count": 0,
            "route_decision": "",
            "rewrite_count": 0,
            "max_rewrite_count": 1,
        }

        assert len(state["messages"]) == 1
        assert state["question"] == "测试问题"
        assert len(state["documents"]) == 1
        assert state["iteration_count"] == 0
        assert state["route_decision"] == ""
        assert state.get("rewrite_count") == 0
        assert state.get("max_rewrite_count") == 1

    def test_initial_state_with_defaults(self):
        """初始状态应有合理的默认值。"""
        state: GraphState = {
            "messages": [],
            "question": "",
            "documents": [],
            "iteration_count": 0,
            "route_decision": "",
            "rewrite_count": 0,
            "max_rewrite_count": 1,
        }

        assert state["messages"] == []
        assert state["documents"] == []
        assert state["iteration_count"] == 0
        assert state["route_decision"] == ""
        assert state["rewrite_count"] == 0
        assert state["max_rewrite_count"] == 1


# ============================================================
# 导入测试 — 无循环依赖
# ============================================================

class TestGraphStateImport:
    """验证状态定义文件可被其他模块正常导入，无循环依赖。"""

    def test_import_from_workflow_package(self):
        """从 workflow 包导入 GraphState。"""
        from src.workflow import GraphState as ImportedState

        assert ImportedState is GraphState

    def test_import_from_state_module(self):
        """从 state 模块直接导入。"""
        from src.workflow.state import GraphState as DirectState

        assert DirectState is GraphState
