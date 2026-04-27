"""core 包 — 核心基础设施：配置管理、工厂函数、异常体系。

公共 API：
    - 配置管理：Settings（配置类）, settings（全局单例）
    - 工厂函数：create_embeddings, create_llm, create_rag_chain, create_retriever, create_vectorstore
    - 异常体系：RAGSystemError（基类）, RetryableError（可重试）, NonRetryableError（不可重试）

设计原则：
    - 工厂模式：统一通过工厂函数创建对象，便于依赖注入和测试
    - 配置驱动：所有对象创建基于 Settings 配置，支持环境变量覆盖
    - 异常层次：区分可重试/不可重试错误，支持上层重试策略
"""

# 配置管理（Pydantic Settings + 全局单例）
from .config import settings
from .settings import Settings

# 异常体系（层次化设计，支持重试策略）
from .exceptions import NonRetryableError, RAGSystemError, RetryableError

# 工厂函数（配置驱动的对象创建）
from .factories import (
    create_embeddings,   # 创建 Embedding 模型实例
    create_llm,          # 创建 LLM 实例
    create_rag_chain,    # 创建完整 RAG 问答链
    create_retriever,    # 创建检索器实例
    create_vectorstore,  # 创建向量库实例
)

__all__ = [
    # 配置管理
    "Settings",      # 配置类定义（Pydantic BaseSettings）
    "settings",      # 全局配置单例（已加载 .env 环境变量）
    # 工厂函数（统一对象创建入口）
    "create_embeddings",
    "create_llm",
    "create_rag_chain",
    "create_retriever",
    "create_vectorstore",
    # 异常体系（支持重试策略判断）
    "RAGSystemError",      # 所有 RAG 异常的基类
    "RetryableError",      # 可重试异常（429、5xx 等）
    "NonRetryableError",   # 不可重试异常（401、400 等）
]
