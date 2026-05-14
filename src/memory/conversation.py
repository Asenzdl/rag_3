"""对话消息裁剪工具 — 使用 LangChain 内置 trim_messages 实现滑动窗口。

设计意图：
    trim_messages 是 LangChain 内置的消息裁剪工具，封装了"保留最近 N tokens"
    的滑动窗口逻辑。本项目将其封装为 trim_conversation_history，提供项目级
    的默认参数和常量。

为什么是独立文件而非在 nodes.py 内联（功能取舍）：
    1. trim_conversation_history 是纯函数——不需要 LLM、不需要状态适配。
       放在 nodes.py 会与 LangGraph 节点代码混在一起，不利于独立测试。
    2. 与 routing.py（纯函数）→ nodes.py（route_node 包装）的模式一致。
"""

from langchain_core.messages import BaseMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages

KEEP_LAST_N: int = 4
"""摘要时保留的最近消息轮数（Human+AI 算一轮）。

选 4 轮的理由：
    - 保留 4 轮共 8 条消息，约 800 tokens（按平均每轮 100 tokens 估算）
    - 加摘要约 200 tokens + 当前轮 prompt 约 500 tokens + 文档上下文约 1500 tokens
    - 总计约 3000 tokens，max_tokens=4000 有 1000 余量

为什么选偶数（非关键决策）：
    不会出现 4.5 轮这种非整数——4 轮总是 8 条消息，对称完整。
"""


def trim_conversation_history(
    messages: list[BaseMessage],
    *,
    max_tokens: int,
) -> list[BaseMessage]:
    """裁剪消息列表使其 token 总数不超过 max_tokens。

    使用 LangChain 内置 trim_messages 的 "last" 策略：
    保留最近的消息直到 token 数 ≤ max_tokens。

    为什么用 start_on="human" + end_on=("human",) 双约束（陷阱规避）：
        start_on 确保保留的第一个消息是 HumanMessage——避免以 AI 消息开头的
        不完整对话。end_on 确保保留的最后一个消息是 HumanMessage——因为 LLM
        的 chat_history 需要在 HumanMessage 后拼接当前轮的 HumanMessage，
        如果最后一条是 AIMessage，拼接后会出现"AI→Human"的反直觉顺序。
        end_on 是包含性约束——列表的末端是一条 HumanMessage，而不是在它之后截断。

    为什么 include_system=True（设计决策）：
        SystemMessage 包含全局行为指令（角色定义、引用格式要求），
        缺失 SystemMessage 会导致 LLM 的输出格式退化。
        include_system=True 确保第一条 SystemMessage 始终被保留。

    Args:
        messages: 待裁剪的消息列表（原文不会被修改——trim_messages 返回子集视图）
        max_tokens: 裁剪后最大 token 数

    Returns:
        保留的消息子集（原对象的引用，ID 不变）
    """
    return trim_messages(
        messages,
        strategy="last",
        token_counter=count_tokens_approximately,
        max_tokens=max_tokens,
        start_on="human",
        end_on=("human",),
        include_system=True,
    )
