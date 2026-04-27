"""RAG 系统统一异常体系。

设计意图：
    为整个 RAG 系统提供分层异常基类。上层调用方（CLI/FastAPI/LangGraph）
    可通过捕获 RAGSystemError 统一处理所有系统异常，也可通过捕获
    RetryableError/NonRetryableError 做重试决策。

异常层次：
    RAGSystemError                    # 公共基类（统一捕获点）
    ├── GenerationError               # 生成模块异常（定义在 generation/exceptions.py）
    │   ├── LLMCallError              # LLM 调用失败
    │   ├── EmptyRetrievalError       # 空检索
    │   └── CitationExtractionError   # 引用提取失败
    ├── RetrievalError                # 检索模块异常（定义在 retriever/base_retriever.py）
    │   └── UnsupportedSearchTypeError
    ├── RetryableError                # 可重试错误标记
    └── NonRetryableError             # 不可重试错误标记

迁移说明：
    Task 1.6 在 generation/exceptions.py 中定义了 GenerationError，继承 Exception。
    Task 1.7 将 GenerationError 的基类从 Exception 改为 RAGSystemError，
    同时将 retriever/base_retriever.py 中的 RetrievalError 基类改为 RAGSystemError。
    具体异常类仍在各自模块定义（模块自治），仅基类统一到 core。
"""



class RAGSystemError(Exception):
    """RAG 系统公共异常基类。

    为什么需要这个基类：
        1. 依赖倒置：上层依赖抽象基类而非具体异常类型，
           切换 LLM 提供商时无需修改异常处理代码
        2. 统一处理：FastAPI 全局异常处理器可注册 RAGSystemError，
           返回统一的错误响应格式（Task 5.1）
        3. LangGraph 路由：条件边可基于异常类型做路由决策
           （Task 2.6 自适应路由）

    上层使用方式：
        # 统一捕获所有系统异常
        try:
            result = chain.invoke(question)
        except RAGSystemError as e:
            # 处理任何 RAG 系统错误
            logger.error("RAG 系统异常", error=str(e))
    """

    pass


class RetryableError(RAGSystemError):
    """可重试错误标记基类。

    为什么用标记基类而非 is_retryable 属性：
        1. tenacity 的 retry_if_exception_type 基于 isinstance 判断，
           继承关系天然支持，无需在每次捕获时检查属性
        2. 异常类型本身携带语义——看到 RetryableError 就知道可重试
        3. 避免在异常实例上添加属性后遗忘设置，导致重试逻辑失效

    使用方式：
        # 自定义可重试异常
        class RateLimitExceeded(RetryableError):
            pass

        # tenacity 自动识别
        @retry(retry=retry_if_exception_type(RetryableError))
        def call_llm(): ...
    """

    pass


class NonRetryableError(RAGSystemError):
    """不可重试错误标记基类。

    什么时候应该继承此类：
        1. 认证/授权失败（401/403）— 重试不会让错误的 Key 变正确
        2. 请求格式错误（400）— 重试同样的错误请求无意义
        3. 配额耗尽（402/422）— 重试只会浪费更多配额
        4. 业务逻辑错误 — 如 EmptyRetrievalError，重试结果相同
    """

    pass

__all__ = [
    "NonRetryableError",
    "RAGSystemError",
    "RetryableError",
]
