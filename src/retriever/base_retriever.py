"""基础向量检索器：封装 Chroma 向量检索器。

本模块提供对 Chroma 向量库的检索封装，包含以下核心设计：

1. **单例向量库连接**：通过 `@lru_cache` 缓存 `Chroma` 实例，避免重复加载 Embedding 模型
   （模型加载耗时较长，单例模式可显著提升多次检索的性能）。

2. **自定义异常体系**：定义 `RetrievalError` 及 `UnsupportedSearchTypeError`，
   将底层异常转换为语义明确的业务异常，便于上层统一处理。

3. **增强的检索器**：继承 LangChain 的 `VectorStoreRetriever`，重写 `_get_relevant_documents`
   以添加结构化日志（查询内容、耗时、结果数量）和异常转换。

使用示例：
    from src.core.factories import create_retriever
    retriever = create_retriever(settings, search_kwargs={"k": 3})
    docs = retriever.invoke("什么是 LangGraph?")
"""

import functools
import time
from typing import Any, Dict, Optional

import structlog
from langchain_chroma import Chroma
from langchain_core.vectorstores import VectorStoreRetriever
from typing import override  # Python 3.12+ 标准库，若低版本需从 typing_extensions 导入

from src.core.exceptions import NonRetryableError, RAGSystemError

logger = structlog.get_logger(__name__)


# ============================================================
# 自定义异常类
# ============================================================

class RetrievalError(RAGSystemError):
    """检索过程中的通用异常基类。

    Task 1.7 改动：基类从 Exception 改为 RAGSystemError，
    上层可捕获 RAGSystemError 统一处理所有系统异常。

    用于包装底层向量库抛出的各类异常（如连接超时、索引损坏等），
    使调用方只需捕获 `RetrievalError` 即可处理所有检索相关错误。
    """
    pass


class UnsupportedSearchTypeError(RetrievalError, NonRetryableError):
    """当传入的 `search_type` 参数不被支持时抛出。

    Task 1.7 改动：同时继承 NonRetryableError，
    因为错误的搜索类型是确定性错误，重试无意义。

    当前支持的搜索类型由 LangChain 的 VectorStoreRetriever 定义：
    - "similarity"：余弦相似度检索
    - "mmr"：最大边际相关性检索
    - "similarity_score_threshold"：带分数阈值的相似度检索
    """
    pass


# ============================================================
# 增强的检索器类
# ============================================================

class VectorRetriever(VectorStoreRetriever):
    """继承原生 VectorStoreRetriever，注入日志记录与异常转换。

    该类不修改检索逻辑，仅包装 `_get_relevant_documents` 方法，
    在调用父类方法前后添加性能计时、结构化日志，并将底层 ValueError
    转换为语义更明确的 `UnsupportedSearchTypeError`。

    使用方式与父类完全一致，可直接替换原有检索器。
    """

    @override
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager,           # type: ignore[no-untyped-def] # LangChain 回调管理器，类型定义复杂，此处忽略
        **kwargs: Any,
    ):
        """执行检索并返回相关文档（带日志与异常处理）。

        Args:
            query: 用户输入的查询字符串。
            run_manager: LangChain 回调运行管理器，用于触发回调事件。
            **kwargs: 传递给父类检索方法的额外参数。

        Returns:
            List[Document]: 检索到的文档列表，按相似度降序排列。

        Raises:
            UnsupportedSearchTypeError: 当 `search_type` 参数值不在支持列表中时抛出。
            RetrievalError: 其他任何检索过程中发生的异常均被包装为此类型。
        """
        start = time.perf_counter()
        try:
            docs = super()._get_relevant_documents(
                query, run_manager=run_manager, **kwargs
            )
            latency_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "检索成功",
                query=query,
                retrieval_count=len(docs),
                latency_ms=round(latency_ms, 1),
                search_type=self.search_type,
            )
            return docs
        except ValueError as e:
            # 父类的 search_type 校验失败时会抛出 ValueError，转换为自定义异常
            raise UnsupportedSearchTypeError(str(e)) from e
        except Exception as e:
            logger.error("检索失败", query=query[:50], error=str(e))
            raise RetrievalError(f"检索失败: {e}") from e


# ============================================================
# 向量库单例获取函数
# ============================================================

@functools.lru_cache(maxsize=4)
def get_vectorstore(
    persist_directory: str = "db/langchain_docs_db1",
    collection_name: str = "langchain_docs1",
    embedding_function: Optional[Any] = None,
) -> Chroma:
    """获取 Chroma 向量库实例（单例模式）。

    使用 `functools.lru_cache` 缓存已创建的 Chroma 对象。对于相同的
    `persist_directory` 和 `collection_name` 组合，只会初始化一次。
    这避免了重复加载 Embedding 模型（Ollama 模型加载开销较大），
    在多次检索调用中显著提升性能。

    Task 1.10 改动：新增 embedding_function 参数（依赖注入），
    不再从 config 导入 ollama_embeddings，由调用方显式传入。

    Args:
        persist_directory: Chroma 数据持久化目录路径。
        collection_name: Chroma 集合名称，同一目录下可存在多个集合。
        embedding_function: Embeddings 实例（由 create_embeddings 创建）。

    Returns:
        已连接并加载 Embedding 函数的 Chroma 向量库实例。

    Note:
        `maxsize=4` 可根据实际需要调整，用于限制缓存的不同向量库实例数量。
    """
    if embedding_function is None:
        raise ValueError(
            "embedding_function 不能为 None，请通过 create_embeddings(settings) 获取实例后传入"
        )
    return Chroma(
        persist_directory=persist_directory,
        collection_name=collection_name,
        embedding_function=embedding_function,
    )


# ============================================================
# 检索器工厂函数
# ============================================================

def create_vector_retriever(
    persist_directory: str = "db/langchain_docs_db1",
    collection_name: str = "langchain_docs1",
    search_type: str = "similarity",
    search_kwargs: Optional[Dict[str, Any]] = None,
    embedding_function: Optional[Any] = None,
) -> VectorRetriever:
    """创建并返回配置好的 VectorRetriever 实例。

    这是一个工厂函数，封装了向量库获取与检索器实例化的过程。
    默认返回 Top-5 相似度检索器。

    Task 1.10 改动：新增 embedding_function 参数（依赖注入），
    不再从 config 导入 ollama_embeddings，由调用方显式传入。

    Args:
        persist_directory: Chroma 数据目录，传递给 `get_vectorstore`。
        collection_name: Chroma 集合名称，传递给 `get_vectorstore`。
        search_type: 检索类型，支持 "similarity"、"mmr" 或 "similarity_score_threshold"。
        search_kwargs: 传递给底层检索器的额外参数。若未提供，默认设置 `{"k": 5}`。
            常用参数示例：
            - `k`: 返回文档数量
            - `score_threshold`: 相似度阈值（仅当 search_type="similarity_score_threshold" 时有效）
            - `fetch_k`: MMR 算法中的候选池大小
            - `lambda_mult`: MMR 算法中的多样性权重
        embedding_function: Embeddings 实例（由 create_embeddings 创建）。

    Returns:
        VectorRetriever: 已配置好向量库连接、检索类型和参数的检索器实例。

    Raises:
        UnsupportedSearchTypeError: 当 `search_type` 不被支持时（由检索器内部抛出）。
    """
    vectorstore = get_vectorstore(
        persist_directory, collection_name, embedding_function=embedding_function
    )

    # 复制字典以避免修改调用方的原始对象
    kwargs = search_kwargs.copy() if search_kwargs else {}
    # 设置默认返回文档数量为 5
    kwargs.setdefault("k", 5)

    return VectorRetriever(
        vectorstore=vectorstore,
        search_type=search_type,
        search_kwargs=kwargs,
    )

__all__ = [
    "RetrievalError",
    "UnsupportedSearchTypeError",
    "VectorRetriever",
]
