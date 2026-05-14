"""
指数退避重试装饰器 — Learning 版

本文件不是为了"This is how you write a retry",
而是为了展示：一个看似简单的工具，把它推到生产级时有哪些维度的权衡。

我们从一个最简单的版本开始，逐层叠加考量。
"""
import time
import functools
import random
from typing import Tuple, Optional


# ── V1：最小可行版本（你已经在 Default 中看到了） ──────────────────────────
# 为什么它不够？往下看。

# ── V2：加入抖动的版本 ────────────────────────────────────────────────────
#
# 问题：如果 100 个客户端同时失败，它们都用 backoff ** attempt 的公式，
#       会在完全相同的时刻发起重试——这叫"惊群效应"(thundering herd)。
#       等于是你在服务最脆弱的时候给了它一个精准齐射。
#
# 解法：加随机抖动 jitter，把重试时间散开。
#       注意——不是"加些随机数"，而是选择一个有意义的抖动策略。
#
# 两种主流策略：
#   Full jitter:  sleep(random.uniform(0, delay))
#     优点：最大程度打散，负载均匀
#     代价：最坏情况退化为立即重试，退避效果削弱
#   Equal jitter: sleep(delay / 2 + random.uniform(0, delay / 2))
#     中间路线：保证至少 delay/2 的等待，同时引入分散
#
# 这里我们选择 full jitter——在"保护下游"和"快速恢复"之间偏向前者。
# 如果你在低延迟场景，Equal jitter 更稳妥。


def retry_v2(
    max_attempts: int = 3,
    backoff: float = 2.0,
    delay: float = 1.0,
    jitter: bool = True,
):
    """
    带 full jitter 的指数退避。

    Parameters
    ----------
    max_attempts : 最大尝试次数（含首次），默认 3
    backoff : 退避乘数，默认 2.0
    delay : 初始等待秒数，默认 1.0
    jitter : 是否启用 full jitter，默认 True
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        # 基础指数退避
                        sleep_time = delay * (backoff ** attempt)
                        # full jitter：[0, sleep_time) 区间均匀采样
                        if jitter:
                            sleep_time = random.uniform(0, sleep_time)
                        time.sleep(sleep_time)
            raise last_exc
        return wrapper
    return decorator


# ── V3：可配置异常类型的版本 ──────────────────────────────────────────────
#
# 当前版本捕获所有 Exception，包括 Coding mistakes（比如 TypeError）
# 和 不可恢复的错误（比如 400 Bad Request 不会因重试变 200）。
#
# 更精确的做法：只重试指定的异常类型。
# 这遵循"Fail Fast"原则——对于注定失败的请求，不要浪费时间和资源。
#
# 另一个边界：自定义异常被装饰器吞掉是否合理？
# 调用者看到的永远是最后一个 Exception 的 traceback，
# 中间失败的 traceback 丢失了——这对调试不友好。
# 生产级做法：重试间隔记录 warning 日志，最终失败时用异常链保留上下文。


def retry_v3(
    max_attempts: int = 3,
    backoff: float = 2.0,
    delay: float = 1.0,
    jitter: bool = True,
    exceptions: Optional[Tuple[type, ...]] = None,
):
    """
    可指定重试异常类型的指数退避装饰器。

    只对 exceptions 中的异常类型重试，其他异常透传。
    """
    if exceptions is None:
        exceptions = (Exception,)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        sleep_time = delay * (backoff ** attempt)
                        if jitter:
                            sleep_time = random.uniform(0, sleep_time)
                        time.sleep(sleep_time)
                except Exception as e:
                    # 不在重试白名单中——立即失败
                    raise e
            raise last_exc
        return wrapper
    return decorator


# ── V4：加日志 + 异常链（生产级底线） ────────────────────────────────────
#
# 到此为止你可以看到一个清晰的演进路径：
#   好用 → 防惊群 → 精确重试 → 可观测
#
# 这不是说你必须每次写出 V4，而是告诉你：
# 当你说"生产级 retry"时，你知道你在省略什么、为什么可以省略。
# 教育的目的不是背答案，是建立判断力。


# ── 设计决策复盘（这是 Learning 模式的真正输出） ─────────────────────────
#
# Q: 为什么要用装饰器而不是上下文管理器？
# A: 装饰器和重试语义更贴——"这个函数应该被重试"是函数本身的属性。
#    上下文管理器适合"这段代码需要重试"，是一次性的。
#    选型依据：语义匹配度。
#
# Q: 为什么要用 time.sleep 而不是 asyncio.sleep？
# A: 这是同步版本。异步版本需要完全不同的实现（await asyncio.sleep）。
#    如果你同时需要同步/异步支持，考虑分成两个装饰器或检测协程。
#
# Q: max_attempts 的合理默认值是多少？
# A: 取决于场景：
#    - 网络请求：3-5 次
#    - 数据库连接：无穷+超时上限（连接池模式）
#    - 幂等操作：可以多试；非幂等操作：最多 1 次
#    "3"是经验值，不是数学结论。
