"""utils 包 — 基础设施工具模块。

提供重试机制和结构化日志等基础设施，供业务模块使用。
"""

from .retry import (
    RetryableError,
    NonRetryableError,
    create_llm_retry_decorator,
    with_retry,
)
from .logger import (
    setup_logging,
    bind_request_id,
    unbind_request_id,
)

__all__ = [
    # retry
    "RetryableError",  # 从 core.exceptions 重新导出，方便调用方
    "NonRetryableError",
    "create_llm_retry_decorator",
    "with_retry",
    # logger
    "setup_logging",
    "bind_request_id",
    "unbind_request_id",
]
