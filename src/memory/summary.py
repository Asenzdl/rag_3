"""对话摘要压缩工具 — 调用 LLM 将早期对话压缩为一段摘要。

设计意图：
    本模块实现 LangGraph 官档的 summarize_conversation 模式，将已有摘要
    和新消息发给 LLM 进行增量扩展。增量而非全量是性能关键——每次 LLM 调用
    只处理新增消息（KEEP_LAST_N 条），不重新处理已压缩的历史。

为什么独立文件而非在 nodes.py 内联（设计决策）：
    summarize_conversation 持有 LLM 调用的 Prompt 模板和业务逻辑。
    放在独立文件中：
    1. 修改摘要 Prompt 不需要动 workflow 代码
    2. 可单独对 Prompt 模板做单元测试
    3. 如果未来独立配置摘要 LLM 模型，只改此文件
"""

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

logger = structlog.get_logger(__name__)

_SUMMARY_SYSTEM_PROMPT = (
    "你是一个对话摘要助手。你的任务是将对话历史压缩为一段简洁的摘要，"
    "保留关键信息（用户问题、系统回答的核心结论）。摘要用中文。"
)
"""系统指令：定义摘要任务的角色和目标。"""


def summarize_conversation(
    messages: list[BaseMessage],
    llm: BaseChatModel,
    existing_summary: str,
    *,
    keep_last_n: int = 4,
) -> tuple[str, list[BaseMessage]]:
    """将消息列表增量压缩为摘要，返回(新摘要文本, 应保留的消息子集)。

    遵循 LangGraph 官档增量扩展模式：
        1. 分离待压缩历史（前 len-KEEP_LAST_N 条）和保留的最新消息
        2. 判断已有摘要是否存在，构造对应 prompt
        3. 调用 LLM 生成/扩展摘要
        4. 返回(新摘要文本, 保留的消息子集)

    为什么返回保留的消息子集而非 RemoveMessage（职责分配）：
        summarize_conversation 只负责摘要逻辑——它告诉调用方"哪些消息应保留"。
        构造 RemoveMessage 是 memory_node 的职责，因为 memory_node 持有
        state 引用，知道消息 ID。这保持了两层的职责边界。

    Args:
        messages: 完整消息列表（包含所有历史 + 当前轮 HumanMessage）
        llm: 用于摘要的 LLM 实例（闭包注入，可 Mock）
        existing_summary: 已有摘要文本（空字符串表示无摘要）
        keep_last_n: 保留的最新消息条数

    Returns:
        (new_summary, kept_messages) 二元组：
        - new_summary: LLM 生成的新摘要文本
        - kept_messages: 保留的最近消息列表（原对象引用，ID 不变）

    Raises:
        LLM 调用失败时重抛异常——memory_node 据此降级到 trim。
        不在此函数内捕获，因为"摘要失败怎么办"是调用方的策略决策。
    """
    # 步骤 1：分离 SystemMessage（始终保留，不参与摘要）
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    # 步骤 2：分离待压缩消息和保留消息
    #   保留最近 keep_last_n 轮对话，其余压缩
    #   保留的最后一条必须是 HumanMessage（当前轮用户的输入）
    to_compress = non_system[:-keep_last_n] if len(non_system) > keep_last_n else []
    kept = non_system[-keep_last_n:] if to_compress else non_system

    if not to_compress:
        # 消息太少，无需压缩
        return existing_summary, messages

    # 步骤 3：构建摘要 prompt
    #   ├─ existing_summary 非空 → 构造增量扩展 prompt
    #   │     LLM 看到"已有摘要 + 新对话"，输出扩展后的新摘要
    #   └─ existing_summary 为空 → 构造创建 prompt
    #         LLM 看到完整对话历史，输出初始摘要
    if existing_summary:
        content = (
            f"这是已有的对话摘要：\n{existing_summary}\n\n"
            f"以下是需要合并到摘要中的新对话：\n"
            f"{_format_messages(to_compress)}\n\n"
            "请扩展已有摘要，将新对话合并进去。保持摘要简洁。"
        )
    else:
        content = (
            f"以下是需要摘要的对话历史：\n{_format_messages(to_compress)}\n\n"
            "请将以上对话压缩为一段简洁的摘要。"
        )

    # 步骤 4：调用 LLM
    prompt = [
        SystemMessage(content=_SUMMARY_SYSTEM_PROMPT),
        HumanMessage(content=content),
    ]
    response = llm.invoke(prompt)
    new_summary = response.content

    # 步骤 5：组装保留消息并返回
    # kept 中不包含 to_compress（已压缩到摘要中）
    # system_msgs 始终保留在最前
    result_messages = system_msgs + kept

    logger.info(
        "摘要完成",
        existing_len=len(existing_summary),
        new_len=len(new_summary),
        is_incremental=bool(existing_summary),
        compressed_count=len(to_compress),
        kept_count=len(kept),
    )

    return new_summary, result_messages


def _format_messages(messages: list[BaseMessage]) -> str:
    """将消息列表格式化为摘要 LLM 可读的文本。

    每条消息用"角色: 内容"格式，便于 LLM 理解对话轮次。
    """
    parts = []
    for msg in messages:
        role = "Human" if isinstance(msg, HumanMessage) else "AI"
        parts.append(f"{role}: {msg.content}")
    return "\n\n".join(parts)
