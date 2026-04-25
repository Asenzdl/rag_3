"""core 包 — 核心功能模块：配置管理、工厂函数、异常体系。"""

from .config import settings
from .exceptions import NonRetryableError, RAGSystemError, RetryableError
from .factories import (
    create_embeddings,
    create_llm,
    create_rag_chain,
    create_retriever,
    create_vectorstore,
)
from .settings import Settings

__all__ = [
    # settings
    "Settings",
    "settings",
    # factories
    "create_embeddings",
    "create_llm",
    "create_rag_chain",
    "create_retriever",
    "create_vectorstore",
    # exceptions
    "RAGSystemError",
    "RetryableError",
    "NonRetryableError",
]
