"""LLM 调用重试机制。

设计意图：
    使用 tenacity 库实现可配置的指数退避重试策略，核心关注点：
    1. 错误分类：区分可重试错误（429/5xx/超时）和不可重试错误（401/400）
    2. 重试日志：每次重试记录 attempt、wait_time、error 信息
    3. 配置外部化：重试参数（次数、等待范围）通过函数参数注入

为什么用 tenacity 而非手写重试：
    1. 指数退避 + 抖动的数学计算容易写错（tenacity 内置正确实现）
    2. 装饰器模式简洁，不侵入业务逻辑
    3. 社区广泛使用，面试时能讲清原理即可

为什么不用 LangChain 的 with_retry：
    1. Task 1.7 要求展示 tenacity 原生用法（面试要求）
    2. with_retry 的回调机制不如 tenacity 灵活（无法自定义日志格式）
    3. with_retry 底层也用 tenacity，直接使用 tenacity 更透明
"""

from typing import Callable, TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

import structlog

from src.core.exceptions import NonRetryableError, RetryableError

logger = structlog.get_logger(__name__)

T = TypeVar("T")


def _is_retryable_error(exc: BaseException) -> bool:
    """判断异常是否可重试。

    判断策略（按优先级短路求值）：
        步骤 1：异常是 NonRetryableError 子类 → return False
            NonRetryableError 是显式声明，优先级最高
        步骤 2：异常是 RetryableError 子类 → return True
            RetryableError 是显式声明，优先级次高
        步骤 3：遍历 __cause__ 链（最多 5 层，防止无限循环），
            对每个异常检查 status_code 属性：
            - status_code == 429 → return True（Rate Limit，可重试）
            - 500 <= status_code < 600 → return True（服务器错误，可重试）
            - 400 <= status_code < 500 → return False（客户端错误，不可重试）
        步骤 4：检查异常类名是否包含超时/连接关键词：
            - 类名含 "Timeout" → return True
            - 类名含 "Connect" → return True
        步骤 5：默认 return False
            安全默认值：未知错误不重试，避免无意义重试浪费配额

    为什么遍历 __cause__ 链而非只看当前异常：
        LangChain 的 LCEL 链可能将底层 SDK 异常包装为自己的异常类型，
        原始的 status_code 信息保存在 __cause__ 链中。
        例如：langchain 的 ChatModel 抛出的异常可能包装了
        openai.RateLimitError，后者才有 status_code=429。

    Args:
        exc: 待判断的异常对象

    Returns:
        True = 可重试，False = 不可重试
    """
    # 步骤 1：检查 NonRetryableError（显式不可重试，最高优先级）
    if isinstance(exc, NonRetryableError):
        return False

    # 步骤 2：检查 RetryableError（显式可重试）
    if isinstance(exc, RetryableError):
        return True

    # 步骤 3：遍历 __cause__ 链，检查 status_code
    current = exc
    depth = 0
    while current is not None and depth < 5:
        # 步骤 3a：获取 status_code 属性
        # 优先检查 status_code（openai SDK 用此属性名）
        status_code = getattr(current, "status_code", None)
        # 备选检查 http_status（某些 HTTP 库用此属性名）
        if status_code is None:
            status_code = getattr(current, "http_status", None)

        if status_code is not None:
            # 步骤 3b：按状态码分类
            if status_code == 429:
                # 429 Rate Limit → 可重试（服务端限流，稍后可恢复）
                return True
            if 500 <= status_code < 600:
                # 5xx 服务器错误 → 可重试（服务端临时故障）
                return True
            if 400 <= status_code < 500:
                # 4xx 客户端错误（非 429）→ 不可重试（请求本身有问题）
                return False

        # 步骤 3c：沿 __cause__ 链继续查找
        current = current.__cause__
        depth += 1

    # 步骤 4：检查类名模式（超时/连接错误）
    # 为什么用类名而非 isinstance：避免在 utils 层导入特定 SDK 的异常类（依赖倒置）
    exc_type_name = type(exc).__name__
    timeout_keywords = ("Timeout", "APITimeoutError")
    connect_keywords = ("ConnectError", "ConnectionError")
    if any(kw in exc_type_name for kw in timeout_keywords + connect_keywords):
        return True

    # 步骤 5：安全默认值 — 未知错误不重试
    return False


def _log_retry(retry_state: RetryCallState) -> None:
    """tenacity before_sleep 回调：记录重试日志。

    为什么用 before_sleep 回调：
        before_sleep 在"决定重试后、开始等待前"触发，此时：
        - retry_state.attempt_number：已尝试的次数（含本次失败）
        - retry_state.next_action.sleep：即将等待的秒数
        - retry_state.outcome.exception()：触发重试的异常
        这三个信息足以判断重试行为是否正常，也便于在 ELK 中
        按时间线重建重试过程。

    Args:
        retry_state: tenacity 内部状态对象
    """
    # 步骤 1：从 retry_state 提取信息
    attempt = retry_state.attempt_number
    wait_seconds = retry_state.next_action.sleep
    exception = retry_state.outcome.exception()

    # 步骤 2：记录 warning 级别日志
    # 为什么用 warning 而非 info：重试意味着异常发生，值得关注
    logger.warning(
        "LLM 调用失败，准备重试",
        attempt=attempt,
        wait_seconds=round(wait_seconds, 1),
        error=str(exception),
        error_type=type(exception).__name__,
    )


def create_llm_retry_decorator(
    max_attempts: int = 3,
    min_wait: float = 4,
    max_wait: float = 10,
    multiplier: float = 1,
) -> Callable:
    """创建配置好的 LLM 重试装饰器（工厂函数）。

    设计意图：
        封装 tenacity 的配置细节，调用方只需指定业务参数
        （最大重试次数、等待范围），无需了解 tenacity 的
        stop/wait/retry 等原语。

    为什么是工厂函数而非固定装饰器：
        不同场景的重试策略可能不同：
        - LLM 调用：3 次重试，指数退避 4-10s
        - 向量库查询：2 次重试，固定间隔 1s
        工厂函数支持灵活配置，避免硬编码。

    Args:
        max_attempts: 最大尝试次数（含首次调用），默认 3
            含首次调用的含义：max_attempts=3 → 最多重试 2 次
        min_wait: 指数退避最小等待秒数，默认 4
        max_wait: 指数退避最大等待秒数，默认 10
        multiplier: 指数退避乘数，默认 1
            等待时间 = multiplier * 2^(attempt_number-1)，受 min/max 约束
            第1次重试等待: 1*2^1 = 2s → clamp to min_wait = 4s
            第2次重试等待: 1*2^2 = 4s → 4s
            第3次重试等待: 1*2^3 = 8s → 8s

    Returns:
        tenacity 装饰器函数，可直接 @装饰 目标函数

    示例：
        decorator = create_llm_retry_decorator(max_attempts=3)

        @decorator
        def call_api():
            ...
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(
            multiplier=multiplier, min=min_wait, max=max_wait
        ),
        retry=retry_if_exception(_is_retryable_error),
        before_sleep=_log_retry,
        reraise=True,
    )


def with_retry(
    func: Callable[..., T],
    max_attempts: int = 3,
    min_wait: float = 4,
    max_wait: float = 10,
    multiplier: float = 1,
) -> Callable[..., T]:
    """便捷函数：用重试逻辑包装给定函数。

    设计意图：
        RAGChain 的 LLM 调用是实例方法，需要在 __init__ 中
        动态包装（因为 self._prompt_llm_chain 在 __init__ 中创建），
        装饰器无法在实例方法上动态使用，因此提供此便捷函数。

    为什么不直接用 tenacity 的 @retry 装饰器：
        装饰器在类定义时绑定，而重试的函数（self._prompt_llm_chain.invoke）
        在实例化时才可用。with_retry 支持运行时动态包装。

    Args:
        func: 需要重试包装的可调用对象
        max_attempts: 最大尝试次数，默认 3
        min_wait: 最小等待秒数，默认 4
        max_wait: 最大等待秒数，默认 10
        multiplier: 退避乘数，默认 1

    Returns:
        包装后的可调用对象，调用时自动应用重试逻辑

    用法示例：
        # 在 RAGChain.__init__ 中
        self._retryable_invoke = with_retry(
            self._prompt_llm_chain.invoke,
            max_attempts=3,
        )

        # 在 invoke() 中
        ai_message = self._retryable_invoke(
            {"context": context, "question": question}
        )
    """
    decorator = create_llm_retry_decorator(
        max_attempts=max_attempts,
        min_wait=min_wait,
        max_wait=max_wait,
        multiplier=multiplier,
    )
    return decorator(func)

__all__ = [
    "RetryableError",
    "NonRetryableError",
    "create_llm_retry_decorator",
    "with_retry",
]
