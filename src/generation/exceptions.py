"""生成模块异常定义。

设计意图：
    定义生成模块的专用异常体系，将底层 LLM SDK 异常（openai.APIError、
    httpx.HTTPError 等）转换为语义明确的业务异常，上层调用方只需
    捕获 GenerationError 基类即可处理所有生成相关错误。

Task 1.7 改动：
    1. GenerationError 基类从 Exception 改为 RAGSystemError
    2. LLMCallError 增加 is_retryable 属性，供重试机制判断
    3. EmptyRetrievalError 和 CitationExtractionError 继承 NonRetryableError
       （这些错误重试无意义）
"""

from typing import Optional

from src.core.exceptions import NonRetryableError, RAGSystemError


class GenerationError(RAGSystemError):
    """生成模块异常基类。

    为什么继承 RAGSystemError 而非 Exception：
        Task 1.7 统一异常体系后，上层可捕获 RAGSystemError
        统一处理所有系统异常（依赖倒置原则）。
        GenerationError 仍作为生成模块的捕获入口：
        except GenerationError 只捕获生成相关异常。

    为什么需要自定义基类：
        1. 上层调用方只需 except GenerationError 即可统一处理
        2. 可在基类中添加通用行为（如错误码映射、上下文信息格式化）
        3. 便于 LangGraph 节点按异常类型做路由决策

    所有子类异常的 message 应包含：
        - 发生错误的上下文（如问题文本截断）
        - 原始错误信息（如 API 返回的 error message）
    """

    pass


class LLMCallError(GenerationError):
    """LLM API 调用失败时抛出。

    Task 1.7 新增：
        is_retryable 属性标记此异常是否可重试。
        retry.py 的 _is_retryable_error 函数会检查此属性。

    触发场景：
        - 网络超时（openai.APITimeoutError）→ is_retryable=True
        - API Key 无效（openai.AuthenticationError）→ is_retryable=False
        - Rate Limit 超限（openai.RateLimitError）→ is_retryable=True
        - 服务器错误（openai.APIStatusError with 5xx）→ is_retryable=True
        - 连接失败（httpx.ConnectError）→ is_retryable=True

    为什么包装而非直接抛出底层异常：
        1. 调用方不应依赖特定 SDK 的异常类型（依赖倒置）
        2. 切换 LLM 提供商（DeepSeek → Qwen）时无需修改上层代码
        3. 可在包装时附加上下文信息（问题文本、重试次数等）

    Attributes:
        original_error: 被包装的原始异常对象，保留完整堆栈信息，
            便于调试时追溯底层原因
        is_retryable: 是否可重试（供重试机制判断），默认 True
    """

    def __init__(
        self,
        message: str,
        original_error: Optional[Exception] = None,
        is_retryable: bool = True,
    ):
        # 调用父类初始化，传入完整错误消息
        super().__init__(message)
        # 保存原始异常引用，便于日志记录和调试追溯
        self.original_error = original_error
        # 保存可重试标记
        # 为什么默认 True：LLM 调用失败多数是临时性的（网络/限流），
        # 显式设置 is_retryable=False 的场景较少（认证失败等）
        self.is_retryable = is_retryable


class EmptyRetrievalError(GenerationError, NonRetryableError):
    """检索返回空文档列表时抛出（可选）。

    为什么同时继承 GenerationError 和 NonRetryableError：
        - GenerationError：空检索是生成流程中的事件，上层可通过
          except GenerationError 统一捕获
        - NonRetryableError：空检索是确定性的业务结果，重试结果相同，
          不应触发重试

    触发场景：
        用户问题与向量库中的所有文档都不相关，检索器返回空列表。

    为什么是可选异常：
        RAGChain 默认行为是返回预设回复（不抛异常），因为空检索
        是合法的业务场景（用户问了文档范围外的问题）。
        但在某些场景下（如 LangGraph 路由），上层需要知道检索为空
        以走不同的分支（如调用网络搜索工具），
        此时可通过 raise_on_empty=True 配置启用此异常。

    使用方式：
        RAGChain(retriever=..., raise_on_empty=False)  # 默认：返回预设回复
        RAGChain(retriever=..., raise_on_empty=True)   # 抛出 EmptyRetrievalError
    """

    pass


class CitationExtractionError(GenerationError, NonRetryableError):
    """引用提取失败时抛出。

    为什么同时继承 NonRetryableError：
        引用提取失败通常是因为输出格式不符合预期，重试 LLM
        会产生不同的输出（非幂等），且额外 LLM 调用不值得。
        直接返回 citations=[] 的降级结果更合理。

    触发场景：
        - 结构化输出解析失败（模型返回的 JSON 不符合 schema）
        - 正则匹配异常（answer 文本格式严重偏离预期）

    为什么不应中断主流程：
        引用提取是增强功能，回答文本本身仍然有效。
        RAGChain 在调用 CitationExtractor 时应捕获此异常，
        返回 citations=[] 的 RAGResponse，而非让整个请求失败。
    """

    pass

__all__ = [
    "CitationExtractionError",
    "EmptyRetrievalError",
    "GenerationError",
    "LLMCallError",
]
