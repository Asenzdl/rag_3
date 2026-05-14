"""记忆管理工具包 — 对话历史压缩与裁剪。

提供两个核心函数和一个模块常量：
    - trim_conversation_history：滑动窗口裁剪（纯函数，无 LLM 依赖）
    - summarize_conversation：LLM 增量摘要（复用 generate 的 llm 实例）
    - KEEP_LAST_N：摘要时保留的最近消息轮数
"""

from src.memory.conversation import trim_conversation_history, KEEP_LAST_N
from src.memory.summary import summarize_conversation

__all__ = [
    "trim_conversation_history",
    "summarize_conversation",
    "KEEP_LAST_N",
]
