"""Prompt 模板定义与版本管理模块。

本模块负责 RAG 系统的 Prompt 模板工程，核心设计：

1. **跨语言 RAG 支持**：中文提问 → 英文文档检索 → 中文回答（附来源引用），
   System Message 中明确指示语言策略，防止模型混淆语言。

2. **版本管理**：通过 PROMPT_REGISTRY 注册表 + PromptVersion 枚举管理不同版本，
   新增版本只需添加枚举值 + 模板字符串 + 注册，不修改工厂函数逻辑（开闭原则）。

3. **Few-shot 示例**：在 V2 版本中可选启用，通过 (HumanMessage, AIMessage) 对
   动态插入 messages 列表，提升引用格式的遵从度。

4. **对话历史预留**：通过 include_chat_history 参数预留 MessagesPlaceholder，
   为 Task 2.5 对话记忆功能提供标准接口。

使用示例：
    from src.generation.prompts import get_prompt, PromptVersion

    # 获取 V1 基础版模板
    prompt = get_prompt(PromptVersion.V1)

    # 获取 V2 增强版（含 few-shot 示例 + 对话历史）
    prompt = get_prompt(PromptVersion.V2, include_few_shot=True, include_chat_history=True)

    # 在 LCEL Chain 中使用
    chain = prompt | llm
"""

from enum import Enum
from typing import Dict, List

import structlog
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
)

logger = structlog.get_logger(__name__)


# ============================================================
# Prompt 版本枚举
# ============================================================

class PromptVersion(str, Enum):
    """Prompt 版本枚举。

    设计意图：
        使用 str + Enum 继承，使枚举值既可作为字符串比较，
        也可作为字典 key。便于 A/B 测试时通过字符串配置切换版本。

    为什么用枚举而非裸字符串？
        - 类型安全：IDE 自动补全 + 静态检查
        - 防拼写错误：PromptVersion.V1 不会拼错
        - 可扩展：新增版本只需添加枚举值 + 注册模板
    """
    V1 = "v1"   # 基础版：简洁指令，无 few-shot
    V2 = "v2"   # 增强版：含 few-shot 示例，引用格式遵从度更高


# ============================================================
# System Message 模板
# ============================================================

# V1：基础版 — 简洁指令，覆盖角色定义 + 语言策略 + 引用格式 + 幻觉防护
SYSTEM_TEMPLATE_V1 = """你是一个专业的技术文档问答助手。

## 角色定义
- 你基于提供的文档片段回答用户问题
- 回答必须使用中文，即使参考文档是英文

## 引用格式要求
- 在回答中使用 [1], [2] 等标记引用文档片段
- 在回答末尾列出"来源"部分，标明每个引用标记对应的文档 URL

## 幻觉防护
- 如果提供的文档片段不包含回答问题的信息，请如实回答："根据现有文档，我无法回答该问题。"
- 不要编造文档中不存在的信息"""

# V2：增强版 — 更详细的跨语言策略 + 严格的引用格式规范
SYSTEM_TEMPLATE_V2 = """你是一个专业的技术文档问答助手，专门处理跨语言技术问答。

## 角色定义
- 你基于提供的英文文档片段回答用户的中文问题
- 回答必须使用中文，即使参考文档是英文
- 可以保留技术术语的英文原文（如 LangGraph、VectorStore），但解释需用中文

## 跨语言策略
- 用户可能用中文提问关于英文文档的内容
- 你需要理解中文问题，从英文文档中找到相关信息，然后用中文组织回答
- 技术概念翻译优先使用社区通行译法（如"向量存储"而非"矢量仓库"）

## 引用格式要求（严格遵守）
- 在回答中使用 [1], [2] 等行内标记引用文档片段
- 每个引用标记必须在回答末尾的"来源"部分有对应条目
- 来源格式：[N] URL（每个引用占一行）
- 示例：
  来源：
  [1] https://langchain-ai.github.io/langgraph/concepts/low_level/
  [2] https://langchain-ai.github.io/langgraph/how-tos/map_reduce/

## 幻觉防护（严格遵守）
- 如果提供的文档片段不包含回答问题的信息，请如实回答："根据现有文档，我无法回答该问题。"
- 不要编造文档中不存在的信息
- 不要使用你自己的知识库来补充答案，只基于提供的文档片段"""


# ============================================================
# Human Message 模板
# ============================================================

# V1：基础版 — 简洁的上下文 + 问题格式
HUMAN_TEMPLATE_V1 = """参考文档：
{context}

问题：{question}"""

# V2：增强版 — 结构化的上下文格式，每个文档带编号（便于引用标记对应）
HUMAN_TEMPLATE_V2 = """参考文档：
{context}

问题：{question}

请基于以上参考文档回答问题，使用 [1], [2] 等标记引用，并在末尾列出来源。"""


# ============================================================
# Few-shot 示例
# ============================================================

# 为什么需要 Few-shot：
#   仅靠 System 指令描述引用格式，模型的遵从度可能不稳定。
#   加入 1-2 个完整的 Q&A 示例，让模型"看到"期望的输出格式，
#   可显著提升引用标记和来源列表的格式遵从度。
#
# 设计要点：
#   - 示例中的引用格式必须与 System 指令描述严格一致
#   - 示例覆盖典型场景：中文提问 + 英文文档 + 中文回答 + 引用
#   - 作为 (HumanMessage, AIMessage) 对存储，动态插入 messages 列表

FEW_SHOT_EXAMPLES: List[tuple] = [
    (
        HumanMessage(
            content="参考文档：\n"
                    "[1] LangGraph is a framework for building stateful, multi-actor "
                    "applications with LLMs. It extends LangChain with graph-based "
                    "workflow orchestration. "
                    "(source: https://langchain-ai.github.io/langgraph/concepts/low_level/)\n\n"
                    "[2] StateGraph is the core class in LangGraph. You define nodes "
                    "(functions) and edges (transitions) to build your agent workflow. "
                    "(source: https://langchain-ai.github.io/langgraph/how-tos/map_reduce/)\n\n"
                    "问题：LangGraph 是什么？它的核心类是什么？"
        ),
        AIMessage(
            content="LangGraph 是一个用于构建有状态、多参与者 LLM 应用的框架，"
                    "它通过基于图的工作流编排扩展了 LangChain[1]。"
                    "其核心类是 StateGraph，通过定义节点（函数）和边（转换）"
                    "来构建 Agent 工作流[2]。\n\n"
                    "来源：\n"
                    "[1] https://langchain-ai.github.io/langgraph/concepts/low_level/\n"
                    "[2] https://langchain-ai.github.io/langgraph/how-tos/map_reduce/"
        ),
    ),
]


# ============================================================
# Prompt 版本注册表
# ============================================================

PROMPT_REGISTRY: Dict[PromptVersion, Dict[str, str]] = {
    PromptVersion.V1: {
        "system": SYSTEM_TEMPLATE_V1,
        "human": HUMAN_TEMPLATE_V1,
    },
    PromptVersion.V2: {
        "system": SYSTEM_TEMPLATE_V2,
        "human": HUMAN_TEMPLATE_V2,
    },
}
"""Prompt 版本注册表。

设计意图：
    将版本与模板内容的映射关系集中管理，新增版本只需：
    1. 添加 PromptVersion 枚举值
    2. 定义模板字符串
    3. 在注册表中注册
    三步完成，不修改 get_prompt 逻辑（开闭原则）。
"""


# ============================================================
# 内部函数：组装 messages 列表
# ============================================================

def _build_messages(
    system_template: str,
    human_template: str,
    include_few_shot: bool = False,
    include_chat_history: bool = False,
) -> list:
    """组装 ChatPromptTemplate 的 messages 列表。

    消息顺序（LangChain Chat 模型惯例）：
        1. SystemMessage — 全局行为指令（角色、语言、引用格式）
        2. [Few-shot 示例对] — Human + AI 示例（可选，提升格式遵从度）
        3. [MessagesPlaceholder("chat_history")] — 对话历史（可选，Task 2.5 预留）
        4. HumanMessage — 当前问题 + 上下文（核心交互消息，必须在列表末尾）

    为什么 Few-shot 放在 System 和当前 Human 之间：
        这是 Chat 模型的标准 few-shot 位置，模型会模仿紧邻示例的格式。
        放在 System 之前会被"淹没"，放在当前 Human 之后没有意义。

    Args:
        system_template: System Message 模板字符串
        human_template: Human Message 模板字符串
        include_few_shot: 是否插入 Few-shot 示例对
        include_chat_history: 是否插入 chat_history 占位符

    Returns:
        可传给 ChatPromptTemplate.from_messages() 的 messages 列表
    """
    messages = []

    # 第1步：System Message — 全局行为指令
    # 为什么放第一个：System Message 对整个对话生效，定义模型的全局行为框架
    messages.append(SystemMessagePromptTemplate.from_template(system_template))

    # 第2步：Few-shot 示例（可选）
    # 为什么用 HumanMessage/AIMessage 而非 PromptTemplate：
    #   few-shot 示例是固定的完整消息，不需要变量替换，
    #   直接用 Message 对象插入更清晰，也避免与模板变量冲突。
    if include_few_shot:
        for human_msg, ai_msg in FEW_SHOT_EXAMPLES:
            messages.append(human_msg)
            messages.append(ai_msg)

    # 第3步：Chat history 占位符（可选，为 Task 2.5 对话记忆预留）
    # 为什么用 MessagesPlaceholder：
    #   1. 标准的 LangChain 方式，与 LCEL 完美集成
    #   2. 支持动态插入任意数量的历史消息
    #   3. 调用方只需传入 chat_history=[...] 即可
    # 为什么在 HumanMessage 之前：Chat 模型要求当前问题在消息列表末尾，
    #   对话历史必须在当前 Human 消息之前，模型先看到历史再回答当前问题
    # 注意：启用时调用方必须传入 chat_history 参数（即使为空列表 []）
    if include_chat_history:
        messages.append(MessagesPlaceholder("chat_history"))

    # 第4步：Human Message — 当前问题 + 上下文
    # 这是核心交互消息，包含 {context} 和 {question} 变量
    # 为什么必须在列表末尾：Chat 模型的 attention 对末尾 token 权重更高，
    #   当前问题在末尾才能确保模型优先关注当前输入
    messages.append(HumanMessagePromptTemplate.from_template(human_template))

    return messages


# ============================================================
# 公共 API：Prompt 工厂函数
# ============================================================

def get_prompt(
    version: PromptVersion = PromptVersion.V1,
    *,
    include_few_shot: bool = False,
    include_chat_history: bool = False,
) -> ChatPromptTemplate:
    """获取指定版本的 Prompt 模板。

    工厂模式封装模板构建细节，调用方只需关心版本和功能开关，
    无需了解 messages 列表的组装逻辑。

    Args:
        version: Prompt 版本枚举值，默认 V1（基础版）
        include_few_shot: 是否包含 Few-shot 示例（仅 V2 有效，V1 忽略此参数）。
            开启后在 System 和 Human 之间插入示例 Q&A 对，提升引用格式遵从度。
        include_chat_history: 是否包含 chat_history 占位符（为 Task 2.5 预留）。
            开启后调用方需传入 chat_history 参数。

    Returns:
        ChatPromptTemplate: 可直接传入 LCEL Chain 的模板实例，
            支持 .invoke()、.stream() 等标准方法。

    Raises:
        ValueError: 当 version 不在 PROMPT_REGISTRY 中时，
            错误信息包含所有可用版本列表。

    使用示例：
        >>> prompt = get_prompt(PromptVersion.V1)
        >>> prompt.input_variables
        ['context', 'question']

        >>> prompt = get_prompt(PromptVersion.V2, include_few_shot=True)
        >>> # V2 + few-shot，引用格式遵从度更高
    """
    # 边界处理：版本不存在时抛出明确错误，列出可用版本
    if version not in PROMPT_REGISTRY:
        available = [v.value for v in PROMPT_REGISTRY.keys()]
        raise ValueError(
            f"未知的 Prompt 版本: {version}，可用版本: {available}"
        )

    templates = PROMPT_REGISTRY[version]

    # V1 不支持 few-shot：即使传入 include_few_shot=True 也忽略
    # 为什么这样设计：V1 模板指令较简洁，缺少对 few-shot 格式的详细引导，
    # 强行插入示例可能导致格式冲突。V2 的详细指令与 few-shot 配合更好。
    effective_few_shot = include_few_shot and version == PromptVersion.V2

    messages = _build_messages(
        system_template=templates["system"],
        human_template=templates["human"],
        include_few_shot=effective_few_shot,
        include_chat_history=include_chat_history,
    )

    prompt = ChatPromptTemplate.from_messages(messages)

    # 记录 Prompt 创建日志，便于追踪使用的是哪个版本和配置
    logger.info(
        "Prompt 模板已创建",
        version=version.value,
        few_shot=effective_few_shot,
        chat_history=include_chat_history,
        input_variables=prompt.input_variables,
    )

    return prompt
