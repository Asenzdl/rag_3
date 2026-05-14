import time
import functools


def retry(max_attempts=3, backoff=2.0):
    """
    Retry a function on exception with exponential backoff.

    Why exponential backoff: 如果服务过载，立即重试大概率继续失败。
    指数等待让负载有时间恢复，同时也避免在短暂的网络抖动上等待太久。
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
                        # 第 0 次失败等 1s，第 1 次等 2s，第 2 次等 4s...
                        time.sleep(backoff ** attempt)
            # 全部耗尽，抛最后一次异常——调用者能拿到原始错误，无须包装
            raise last_exc
        return wrapper
    return decorator
