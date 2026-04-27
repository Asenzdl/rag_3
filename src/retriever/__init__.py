"""retriever 包 — 检索层核心 API。

核心职责：
    - RetrieverProtocol: 检索器协议（依赖倒置）
    - VectorRetriever: 向量检索器实现（基于 Chroma）
    - Exceptions: 检索模块异常体系

已废弃（不导出）：
    - create_vector_retriever: 旧版工厂函数（已被 src.core.factories.create_retriever 替代）
    - get_vectorstore: 旧版向量库获取函数（已被 src.core.factories.create_vectorstore 替代）

使用示例：
    from src.retriever import VectorRetriever, RetrieverProtocol
    from src.core.factories import create_retriever  # 推荐使用工厂函数

    # 推荐方式：通过工厂函数创建（配置驱动）
    retriever = create_retriever(settings, search_kwargs={"k": 5})

    # 直接使用协议类型（用于类型提示）
    def my_function(retriever: RetrieverProtocol): ...
"""

from .base_retriever import (
    RetrievalError,
    UnsupportedSearchTypeError,
    VectorRetriever,
)
from .protocols import RetrieverProtocol

__all__ = [
    # 协议
    "RetrieverProtocol",
    # 实现
    "VectorRetriever",
    # 异常
    "RetrievalError",
    "UnsupportedSearchTypeError",
]
