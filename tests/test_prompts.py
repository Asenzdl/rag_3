"""Prompt 模板单元测试。

测试策略：
    1. 模板变量校验：确保 input_variables 包含必需的变量
    2. 格式化验证：确保模板可以被正确格式化（变量替换）
    3. 版本管理验证：确保工厂函数和注册表工作正常
    4. Few-shot 开关验证：确保 few-shot 示例正确插入/忽略
    5. Chat history 占位符验证：确保对话历史占位符正确插入
    6. 内容验证：确保模板包含关键指令（跨语言、引用、幻觉防护）
    7. 边界情况：版本不存在、空上下文等
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
)

from src.generation.prompts import (
    FEW_SHOT_EXAMPLES,
    PROMPT_REGISTRY,
    SYSTEM_TEMPLATE_V1,
    SYSTEM_TEMPLATE_V2,
    HUMAN_TEMPLATE_V1,
    HUMAN_TEMPLATE_V2,
    PromptVersion,
    _build_messages,
    get_prompt,
)


# ============================================================
# PromptVersion 枚举测试
# ============================================================

class TestPromptVersion:
    """PromptVersion 枚举的基础验证。"""

    def test_v1_value(self):
        """V1 枚举值为 'v1'。"""
        assert PromptVersion.V1.value == "v1"

    def test_v2_value(self):
        """V2 枚举值为 'v2'。"""
        assert PromptVersion.V2.value == "v2"

    def test_str_enum_behavior(self):
        """继承 str 的枚举可直接作为字典 key。"""
        d = {PromptVersion.V1: "template_v1"}
        assert d[PromptVersion.V1] == "template_v1"

    def test_from_string(self):
        """可通过字符串构造枚举（A/B 测试配置场景）。"""
        assert PromptVersion("v1") == PromptVersion.V1
        assert PromptVersion("v2") == PromptVersion.V2


# ============================================================
# get_prompt() 工厂函数测试
# ============================================================

class TestGetPrompt:
    """get_prompt 工厂函数的全面验证。"""

    # --- 基础功能 ---

    def test_v1_returns_chat_prompt_template(self):
        """get_prompt(V1) 返回 ChatPromptTemplate 实例。"""
        prompt = get_prompt(PromptVersion.V1)
        assert isinstance(prompt, ChatPromptTemplate)

    def test_v2_returns_chat_prompt_template(self):
        """get_prompt(V2) 返回 ChatPromptTemplate 实例。"""
        prompt = get_prompt(PromptVersion.V2)
        assert isinstance(prompt, ChatPromptTemplate)

    def test_default_version_is_v1(self):
        """默认版本为 V1。"""
        prompt = get_prompt()
        # V1 不含 chat_history，input_variables 应为 ['context', 'question']
        assert "context" in prompt.input_variables
        assert "question" in prompt.input_variables

    # --- input_variables 验证 ---

    def test_v1_input_variables(self):
        """V1 模板包含 context 和 question 变量。"""
        prompt = get_prompt(PromptVersion.V1)
        assert set(prompt.input_variables) == {"context", "question"}

    def test_v2_input_variables(self):
        """V2 模板包含 context 和 question 变量。"""
        prompt = get_prompt(PromptVersion.V2)
        assert set(prompt.input_variables) == {"context", "question"}

    def test_v2_with_chat_history_input_variables(self):
        """V2 + chat_history 模板包含 context、question 和 chat_history 变量。"""
        prompt = get_prompt(PromptVersion.V2, include_chat_history=True)
        assert "chat_history" in prompt.input_variables
        assert "context" in prompt.input_variables
        assert "question" in prompt.input_variables

    def test_v1_with_chat_history_input_variables(self):
        """V1 + chat_history 也包含 chat_history 变量。"""
        prompt = get_prompt(PromptVersion.V1, include_chat_history=True)
        assert "chat_history" in prompt.input_variables

    # --- 错误处理 ---

    def test_invalid_version_raises_value_error(self):
        """版本不存在时抛出 ValueError。"""
        with pytest.raises(ValueError, match="未知的 Prompt 版本"):
            get_prompt("nonexistent_version")

    # --- Few-shot 行为 ---

    def test_v1_ignores_few_shot(self):
        """V1 版本忽略 include_few_shot 参数。"""
        prompt_without = get_prompt(PromptVersion.V1, include_few_shot=False)
        prompt_with = get_prompt(PromptVersion.V1, include_few_shot=True)
        # V1 无论是否传入 few_shot，生成的模板应相同
        # 检查 input_variables 相同
        assert prompt_without.input_variables == prompt_with.input_variables
        # 检查 messages 数量相同（V1 不应插入 few-shot 示例）
        assert len(prompt_without.messages) == len(prompt_with.messages)

    def test_v2_with_few_shot_has_more_messages(self):
        """V2 + few_shot 的消息数量比 V2 不含 few_shot 多。"""
        prompt_without = get_prompt(PromptVersion.V2, include_few_shot=False)
        prompt_with = get_prompt(PromptVersion.V2, include_few_shot=True)
        # few-shot 插入了 1 个 (Human, AI) 对 = 2 条额外消息
        assert len(prompt_with.messages) == len(prompt_without.messages) + 2


# ============================================================
# 模板内容验证
# ============================================================

class TestTemplateContent:
    """验证模板内容包含关键指令。"""

    # --- 跨语言指令 ---

    def test_v1_system_contains_language_instruction(self):
        """V1 System 模板包含语言指令（中文回答）。"""
        assert "中文" in SYSTEM_TEMPLATE_V1

    def test_v2_system_contains_cross_language_strategy(self):
        """V2 System 模板包含跨语言策略。"""
        assert "跨语言" in SYSTEM_TEMPLATE_V2
        assert "英文" in SYSTEM_TEMPLATE_V2
        assert "中文" in SYSTEM_TEMPLATE_V2

    # --- 引用格式指令 ---

    def test_v1_system_contains_citation_format(self):
        """V1 System 模板包含引用格式指令。"""
        assert "[1]" in SYSTEM_TEMPLATE_V1
        assert "来源" in SYSTEM_TEMPLATE_V1

    def test_v2_system_contains_citation_format(self):
        """V2 System 模板包含更详细的引用格式指令。"""
        assert "[1]" in SYSTEM_TEMPLATE_V2
        assert "来源" in SYSTEM_TEMPLATE_V2
        assert "URL" in SYSTEM_TEMPLATE_V2

    # --- 幻觉防护 ---

    def test_v1_system_contains_hallucination_guard(self):
        """V1 System 模板包含幻觉防护指令。"""
        assert "无法回答" in SYSTEM_TEMPLATE_V1

    def test_v2_system_contains_hallucination_guard(self):
        """V2 System 模板包含更严格的幻觉防护。"""
        assert "无法回答" in SYSTEM_TEMPLATE_V2
        assert "不要编造" in SYSTEM_TEMPLATE_V2

    # --- Human 模板变量 ---

    def test_human_v1_contains_context_and_question(self):
        """V1 Human 模板包含 {context} 和 {question} 变量。"""
        assert "{context}" in HUMAN_TEMPLATE_V1
        assert "{question}" in HUMAN_TEMPLATE_V1

    def test_human_v2_contains_context_and_question(self):
        """V2 Human 模板包含 {context} 和 {question} 变量。"""
        assert "{context}" in HUMAN_TEMPLATE_V2
        assert "{question}" in HUMAN_TEMPLATE_V2


# ============================================================
# 模板格式化测试
# ============================================================

class TestTemplateFormatting:
    """验证模板可被正确格式化。"""

    def test_v1_format_with_context_and_question(self):
        """V1 模板可以用 context 和 question 格式化。"""
        prompt = get_prompt(PromptVersion.V1)
        result = prompt.invoke({
            "context": "LangGraph is a framework for building stateful applications.",
            "question": "LangGraph 是什么？",
        })
        messages = result.to_messages()
        # 应有 System + Human 两条消息
        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)
        # Human 消息应包含上下文和问题内容
        assert "LangGraph is a framework" in messages[1].content
        assert "LangGraph 是什么" in messages[1].content

    def test_v2_format_with_context_and_question(self):
        """V2 模板格式化正常。"""
        prompt = get_prompt(PromptVersion.V2)
        result = prompt.invoke({
            "context": "Test context content.",
            "question": "测试问题",
        })
        messages = result.to_messages()
        assert len(messages) == 2  # System + Human
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)

    def test_v2_with_few_shot_format(self):
        """V2 + few_shot 模板格式化后包含示例消息。"""
        prompt = get_prompt(PromptVersion.V2, include_few_shot=True)
        result = prompt.invoke({
            "context": "Test context.",
            "question": "测试问题",
        })
        messages = result.to_messages()
        # System + (Few-shot Human + AI) + Human = 4 条消息
        assert len(messages) == 4
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)  # Few-shot Human
        assert isinstance(messages[2], AIMessage)      # Few-shot AI
        assert isinstance(messages[3], HumanMessage)   # 实际 Human

    def test_v2_with_chat_history_format(self):
        """V2 + chat_history 模板格式化时需传入 chat_history。"""
        prompt = get_prompt(PromptVersion.V2, include_chat_history=True)
        result = prompt.invoke({
            "context": "Test context.",
            "question": "测试问题",
            "chat_history": [
                HumanMessage(content="之前的问题"),
                AIMessage(content="之前的回答"),
            ],
        })
        messages = result.to_messages()
        # 应包含 chat_history 中的消息
        history_contents = [m.content for m in messages]
        assert "之前的问题" in history_contents
        assert "之前的回答" in history_contents

    def test_v2_with_empty_chat_history(self):
        """V2 + chat_history 传入空列表不报错。"""
        prompt = get_prompt(PromptVersion.V2, include_chat_history=True)
        result = prompt.invoke({
            "context": "Test.",
            "question": "问题",
            "chat_history": [],
        })
        # 不应抛出异常
        messages = result.to_messages()
        assert len(messages) >= 2  # 至少 System + Human

    def test_format_with_empty_context(self):
        """空上下文时模板格式化正常（模拟检索返回空文档场景）。"""
        prompt = get_prompt(PromptVersion.V1)
        result = prompt.invoke({
            "context": "",
            "question": "测试问题",
        })
        messages = result.to_messages()
        # System 消息包含幻觉防护指令，模型应回答"无法回答"
        assert "无法回答" in messages[0].content


# ============================================================
# 注册表验证
# ============================================================

class TestPromptRegistry:
    """PROMPT_REGISTRY 注册表的完整性验证。"""

    def test_registry_has_both_versions(self):
        """注册表包含 V1 和 V2 两个版本。"""
        assert PromptVersion.V1 in PROMPT_REGISTRY
        assert PromptVersion.V2 in PROMPT_REGISTRY

    def test_registry_entries_have_system_and_human(self):
        """每个注册条目都包含 system 和 human 键。"""
        for version, templates in PROMPT_REGISTRY.items():
            assert "system" in templates, f"{version} 缺少 system 键"
            assert "human" in templates, f"{version} 缺少 human 键"

    def test_registry_templates_are_non_empty(self):
        """所有模板字符串非空。"""
        for version, templates in PROMPT_REGISTRY.items():
            assert templates["system"].strip(), f"{version} system 模板为空"
            assert templates["human"].strip(), f"{version} human 模板为空"


# ============================================================
# Few-shot 示例验证
# ============================================================

class TestFewShotExamples:
    """Few-shot 示例的数据完整性验证。"""

    def test_few_shot_examples_is_non_empty(self):
        """Few-shot 示例列表非空。"""
        assert len(FEW_SHOT_EXAMPLES) > 0

    def test_few_shot_examples_are_message_pairs(self):
        """每个 Few-shot 示例是 (HumanMessage, AIMessage) 对。"""
        for human_msg, ai_msg in FEW_SHOT_EXAMPLES:
            assert isinstance(human_msg, HumanMessage)
            assert isinstance(ai_msg, AIMessage)

    def test_few_shot_ai_contains_citation(self):
        """Few-shot AI 回答包含引用标记 [1]。"""
        for _, ai_msg in FEW_SHOT_EXAMPLES:
            assert "[1]" in ai_msg.content, "Few-shot AI 回答缺少引用标记 [1]"

    def test_few_shot_ai_contains_source_section(self):
        """Few-shot AI 回答包含来源部分。"""
        for _, ai_msg in FEW_SHOT_EXAMPLES:
            assert "来源" in ai_msg.content, "Few-shot AI 回答缺少来源部分"

    def test_few_shot_ai_contains_url(self):
        """Few-shot AI 回答的来源部分包含 URL。"""
        for _, ai_msg in FEW_SHOT_EXAMPLES:
            assert "http" in ai_msg.content, "Few-shot AI 回答来源缺少 URL"


# ============================================================
# _build_messages 内部函数测试
# ============================================================

class TestBuildMessages:
    """_build_messages 内部函数的结构验证。"""

    def test_basic_messages_count(self):
        """不含 few-shot 和 chat_history 时，有 2 条消息（System + Human）。"""
        messages = _build_messages(
            system_template=SYSTEM_TEMPLATE_V1,
            human_template=HUMAN_TEMPLATE_V1,
        )
        assert len(messages) == 2

    def test_with_few_shot_messages_count(self):
        """含 1 个 few-shot 示例时，有 4 条消息（System + FH + FA + Human）。"""
        messages = _build_messages(
            system_template=SYSTEM_TEMPLATE_V2,
            human_template=HUMAN_TEMPLATE_V2,
            include_few_shot=True,
        )
        # System + (Few-shot Human + AI) + Human = 4
        assert len(messages) == 4

    def test_with_chat_history_has_placeholder(self):
        """含 chat_history 时，MessagesPlaceholder 存在且位于 HumanMessagePromptTemplate 之前。"""
        messages = _build_messages(
            system_template=SYSTEM_TEMPLATE_V1,
            human_template=HUMAN_TEMPLATE_V1,
            include_chat_history=True,
        )
        # 找到 MessagesPlaceholder 和 HumanMessagePromptTemplate 的索引
        placeholder_idx = next(
            i for i, m in enumerate(messages) if isinstance(m, MessagesPlaceholder)
        )
        human_idx = next(
            i for i, m in enumerate(messages) if isinstance(m, HumanMessagePromptTemplate)
        )
        assert isinstance(messages[placeholder_idx], MessagesPlaceholder)
        assert placeholder_idx < human_idx

    def test_messages_order(self):
        """消息顺序正确：System → [Few-shot] → ChatHistory → Human。"""
        messages = _build_messages(
            system_template=SYSTEM_TEMPLATE_V2,
            human_template=HUMAN_TEMPLATE_V2,
            include_few_shot=True,
            include_chat_history=True,
        )
        # 第1条：SystemMessagePromptTemplate
        assert isinstance(messages[0], SystemMessagePromptTemplate)
        # 第2-3条：Few-shot Human + AI
        assert isinstance(messages[1], HumanMessage)
        assert isinstance(messages[2], AIMessage)
        # 第4条：MessagesPlaceholder（chat_history 在 Human 之前）
        assert isinstance(messages[3], MessagesPlaceholder)
        # 第5条：HumanMessagePromptTemplate（当前问题在末尾）
        assert isinstance(messages[4], HumanMessagePromptTemplate)

    def test_chat_history_before_human_message(self):
        """MessagesPlaceholder 的索引严格小于 HumanMessagePromptTemplate 的索引。"""
        messages = _build_messages(
            system_template=SYSTEM_TEMPLATE_V1,
            human_template=HUMAN_TEMPLATE_V1,
            include_chat_history=True,
        )
        placeholder_idx = next(
            i for i, m in enumerate(messages) if isinstance(m, MessagesPlaceholder)
        )
        human_idx = next(
            i for i, m in enumerate(messages) if isinstance(m, HumanMessagePromptTemplate)
        )
        assert placeholder_idx < human_idx

    def test_invoke_with_chat_history_correct_order(self):
        """invoke 后消息列表中 chat_history 消息在当前 HumanMessage 之前。"""
        prompt = get_prompt(PromptVersion.V2, include_chat_history=True)
        result = prompt.invoke({
            "context": "Test context.",
            "question": "当前问题",
            "chat_history": [
                HumanMessage(content="历史问题"),
                AIMessage(content="历史回答"),
            ],
        })
        messages = result.to_messages()
        # 找到历史消息和当前 HumanMessage 的位置
        history_question_idx = next(
            i for i, m in enumerate(messages) if m.content == "历史问题"
        )
        current_question_idx = next(
            i for i, m in enumerate(messages)
            if isinstance(m, HumanMessage) and "当前问题" in m.content
        )
        assert history_question_idx < current_question_idx
