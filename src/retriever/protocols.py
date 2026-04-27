"""检索器协议定义 — 结构子类型（Structural Subtyping）。

本模块使用 typing.Protocol 定义检索器的最小行为契约，
任何实现了 invoke(self, query: str) -> List[Document] 方法的类
自动满足协议，无需显式继承。

为什么用 Protocol 而非 ABC：
    1. 非侵入式：VectorRetriever 继承自 LangChain 的 VectorStoreRetriever，
       强制它再继承 ABC 会引入多继承 MRO 问题。Protocol 只看方法签名，
       VectorRetriever 无需修改任何代码即自动满足协议。
    2. 鸭子类型的类型安全版：Protocol 是"结构子类型"——不关心类继承关系，
       只关心"有没有 invoke 方法且签名匹配"。
    3. 依赖倒置的最佳实践：RAGChain 依赖 RetrieverProtocol（抽象），
       而非 VectorRetriever（具体），新增检索器类型时无需修改 RAGChain。
"""

from typing import List, Protocol

from langchain_core.documents import Document


class RetrieverProtocol(Protocol):
    """检索器协议 — 定义检索器的最小行为契约。

    隐式实现验证：
        VectorRetriever 通过 VectorStoreRetriever.invoke 继承链
        → 签名为 invoke(self, query: str) -> List[Document]
        → 自动满足 RetrieverProtocol，无需显式声明

    异常声明（接口契约的一部分）：
        - RetrievalError: 检索过程中的通用异常
        - UnsupportedSearchTypeError: 不支持的搜索类型（NonRetryableError）
    """

    def invoke(self, query: str) -> List[Document]:
        """执行检索并返回相关文档列表。

        Args:
            query: 用户查询字符串

        Returns:
            按相关性排序的文档列表

        Raises:
            RetrievalError: 检索过程中发生异常
            UnsupportedSearchTypeError: 搜索类型不被支持
        """
        ...

__all__ = [
    "RetrieverProtocol",
]
