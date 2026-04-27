"""工厂函数模块 — 配置驱动的对象创建。

本模块封装所有 LLM/Embedding/VectorStore/Retriever/RAGChain 的创建逻辑，
调用方只需传入 Settings 对象即可获取配置好的实例，无需了解构造细节。

核心设计：
1. **配置驱动创建**：工厂函数接收 settings 对象，根据配置动态决定创建何种类型的对象
2. **依赖倒置**：返回抽象类型（VectorStore/BaseChatModel/RetrieverProtocol）而非具体类型
3. **惰性实例化**：工厂函数延迟创建对象，避免模块导入时的副作用
4. **单例缓存**：通过模块级变量缓存 embeddings 和 vectorstore 实例，避免重复初始化
5. **开闭原则**：新增 LLM 提供商只需在 create_llm 中添加 elif 分支，不修改调用方

使用方式：
    from src.core.config import settings
    from src.core.factories import create_rag_chain

    chain = create_rag_chain(settings)
"""

from typing import Any, Dict, List, Optional

import structlog
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.vectorstores import VectorStore

from src.core.exceptions import NonRetryableError
from src.core.settings import Settings
from src.retriever.protocols import RetrieverProtocol

logger = structlog.get_logger(__name__)


# ============================================================
# 单例缓存（模块级变量，避免重复初始化）
# ============================================================

_embeddings_cache: Optional[Any] = None  # Embeddings 实例缓存
_vectorstore_cache: Optional[VectorStore] = None  # VectorStore 实例缓存
_llm_cache: Dict[str, BaseChatModel] = {}  # 按 provider 缓存 LLM 实例


# ============================================================
# 工厂函数
# ============================================================


def create_embeddings(settings: Settings) -> Any:
    """根据 settings 创建 Ollama Embeddings 实例（单例缓存）。

    为什么缓存：OllamaEmbeddings 初始化会加载模型（耗时较长），
        多次创建同一配置的实例浪费资源。

    为什么用模块级变量而非 @lru_cache：
        Settings 是 Pydantic BaseModel（frozen=False），不可 hash，
        不能作为 @lru_cache 的参数。模块级变量更灵活。

    Args:
        settings: Settings 配置实例

    Returns:
        OllamaEmbeddings 实例
    """
    global _embeddings_cache

    if _embeddings_cache is not None:
        return _embeddings_cache

    from langchain_ollama import OllamaEmbeddings

    _embeddings_cache = OllamaEmbeddings(
        model=settings.embedding_model,
        base_url=settings.ollama_base_url,
    )
    logger.info(
        "Embeddings 实例创建",
        model=settings.embedding_model,
        base_url=settings.ollama_base_url,
    )
    return _embeddings_cache


def create_vectorstore(
    settings: Settings, embedding_function: Any
) -> VectorStore:
    """根据 settings 创建向量库实例（返回 VectorStore 抽象类型，单例缓存）。

    为什么返回 VectorStore 而非 Chroma：
        依赖倒置——调用方（检索器、评估器）依赖抽象类型，
        后续切换为 FAISS/Pinecone 时调用方代码无需修改。

    Args:
        settings: Settings 配置实例
        embedding_function: Embeddings 实例（由 create_embeddings 创建）

    Returns:
        VectorStore 实例

    Raises:
        NonRetryableError: 不支持的向量库类型
    """
    global _vectorstore_cache

    if _vectorstore_cache is not None:
        return _vectorstore_cache

    if settings.vectorstore_type == "chroma":
        from langchain_chroma import Chroma

        _vectorstore_cache = Chroma(
            persist_directory=settings.chroma_persist_directory,
            collection_name=settings.chroma_collection_name,
            embedding_function=embedding_function,
        )
    else:
        raise NonRetryableError(
            f"不支持的向量库类型: {settings.vectorstore_type}"
        )

    logger.info(
        "VectorStore 实例创建",
        vectorstore_type=settings.vectorstore_type,
        persist_directory=settings.chroma_persist_directory,
        collection_name=settings.chroma_collection_name,
    )
    return _vectorstore_cache


def create_retriever(
    settings: Settings,
    search_type: str = "similarity",
    search_kwargs: Optional[Dict[str, Any]] = None,
) -> RetrieverProtocol:
    """根据 settings 创建检索器实例（返回 RetrieverProtocol 协议类型）。

    为什么返回 RetrieverProtocol 而非 VectorRetriever：
        依赖倒置——消费方（RAGChain、RetrievalEvaluator）依赖协议而非具体类型，
        新增检索器实现时无需修改消费方代码。

    Args:
        settings: Settings 配置实例
        search_type: 检索类型，默认 "similarity"
        search_kwargs: 检索参数，默认 {"k": 5}

    Returns:
        满足 RetrieverProtocol 的检索器实例
    """
    from src.retriever.base_retriever import VectorRetriever

    embeddings = create_embeddings(settings)
    vectorstore = create_vectorstore(settings, embeddings)

    kwargs = search_kwargs.copy() if search_kwargs else {}
    kwargs.setdefault("k", 5)

    retriever = VectorRetriever(
        vectorstore=vectorstore,
        search_type=search_type,
        search_kwargs=kwargs,
    )
    logger.info(
        "Retriever 实例创建",
        search_type=search_type,
        search_kwargs=kwargs,
    )
    return retriever  # type: ignore[return-value]


def create_llm(provider: str, settings: Settings) -> BaseChatModel:
    """根据 provider 和 settings 创建 LLM 实例（单例缓存）。

    为什么参数是 provider 字符串而非枚举：
        字符串更灵活，后续新增提供商无需修改枚举定义。
        但在工厂函数内部做校验，不支持的 provider 立即报错。

    Args:
        provider: LLM 提供商名称（"deepseek" / "qwen"）
        settings: Settings 配置实例

    Returns:
        BaseChatModel 实例

    Raises:
        NonRetryableError: 不支持的 LLM 提供商
    """
    if provider in _llm_cache:
        return _llm_cache[provider]

    from langchain.chat_models import init_chat_model

    if provider == "deepseek":
        llm = init_chat_model(
            model="deepseek-chat",
            model_provider="deepseek",
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            streaming=True,
            temperature=0,
        )
    elif provider == "qwen":
        llm = init_chat_model(
            model="qwen3.5-plus",
            model_provider="dashscope",
            api_key=settings.qwen_api_key,
            base_url=settings.qwen_base_url,
            streaming=True,
            temperature=0,
        )
    else:
        raise NonRetryableError(f"不支持的 LLM 提供商: {provider}")

    _llm_cache[provider] = llm
    logger.info("LLM 实例创建", provider=provider)
    return llm


def create_rag_chain(settings: Settings) -> Any:
    """一行创建完整 RAGChain — 封装检索器 + LLM + Prompt 的组装逻辑。

    为什么不直接在 app.py 中组装：
        1. 单一入口：所有消费方（app.py、测试、未来 FastAPI）统一走此函数
        2. 配置驱动：settings 对象决定创建什么组件，调用方无需了解细节
        3. 可测试性：测试可通过传入 Mock 的 settings 创建定制化 RAGChain

    Args:
        settings: Settings 配置实例

    Returns:
        RAGChain 实例
    """
    # 延迟导入避免循环依赖
    from src.generation.prompts import PromptVersion, get_prompt
    from src.generation.rag_chain import RAGChain

    retriever = create_retriever(settings)
    llm = create_llm(settings.llm_provider, settings)
    prompt = get_prompt(PromptVersion.V2, include_few_shot=True)

    chain = RAGChain(retriever=retriever, llm=llm, prompt=prompt)
    logger.info("RAGChain 创建完成")
    return chain

__all__ = [
    "create_embeddings",
    "create_llm",
    "create_rag_chain",
    "create_retriever",
    "create_vectorstore",
]
