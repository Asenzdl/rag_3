"""测试基础向量检索器。

Task 1.10 改动：create_vector_retriever 新增 embedding_function 参数（依赖注入），
测试改为通过 create_retriever(settings) 工厂函数创建检索器。

metadata 格式如下：
metadata={
    'lastmod': '2026-04-02 18:28:11.931000+00:00',
    'chunk_index': 0,
    'description': '',
    'source': 'https://docs.langchain.com/oss/python/langgraph/local-server',
    'title': 'Run a local server - Docs by LangChain',
    'h1': 'Run a local server',
    'file_path': 'data\\langchain_docs_separated\\oss\\python\\langgraph\\local-server.md',
    'doc_category': 'oss/python',
    'doc_id': 'eea49b6ae0ce65aa',
    'has_code': False,
    'doc_type': 'guide',
    'language': 'en',
    'code_language': ''
}
"""

from src.core.config import settings
from src.core.factories import create_retriever


def test_scheme():
    print("=" * 60)
    print("测试基础向量检索器 create_retriever(settings)")
    print("=" * 60)

    # 通过工厂函数创建检索器
    retriever = create_retriever(
        settings,
        search_type="similarity",
        search_kwargs={"k": 3},
    )

    # 测试查询
    query = "什么是 LangGraph？"
    print(f"\n查询: {query}")
    print(f"检索器类型: {type(retriever).__name__}")

    # 执行检索
    docs = retriever.invoke(query)

    print(f"\n返回文档数: {len(docs)}")
    for i, doc in enumerate(docs, 1):
        print(f"\n--- 文档 {i} ---")
        print(f"内容预览: {doc.page_content[:100]}...")
        # 打印元数据
        print(f"Metadata={doc.metadata}")
        print(f"Metadata: source={doc.metadata.get('source', 'N/A')}")
        print(f"          title={doc.metadata.get('title', 'N/A')}")
        print(f"          chunk_index={doc.metadata.get('chunk_index', 'N/A')}")


def test_mmr():
    """测试 MMR 去重。"""
    print("\n" + "=" * 60)
    print("测试 MMR 去重检索")
    print("=" * 60)

    # 通过工厂函数创建 MMR 检索器
    retriever = create_retriever(
        settings,
        search_type="mmr",
        search_kwargs={"k": 5, "lambda_mult": 0.5},
    )

    query = "LangGraph 的持久化功能"
    print(f"\n查询: {query}")
    print(f"搜索类型: MMR (lambda_mult=0.5)")

    docs = retriever.invoke(query)
    print(f"\n返回文档数: {len(docs)}")
    for i, doc in enumerate(docs, 1):
        print(f"\n--- 文档 {i} ---")
        print(f"内容预览: {doc.page_content[:100]}...")


def test_metadata_filter():
    """测试 Metadata 过滤。"""
    print("\n" + "=" * 60)
    print("测试 Metadata 过滤")
    print("=" * 60)

    # 通过工厂函数创建带过滤的检索器
    retriever = create_retriever(
        settings,
        search_kwargs={"k": 5, "filter": {"doc_category": "oss/python"}},
    )

    query = "RAG 是什么？"
    print(f"\n查询: {query}")
    print(f"过滤条件: doc_category=oss/python")

    docs = retriever.invoke(query)
    print(f"\n返回文档数: {len(docs)}")
    for i, doc in enumerate(docs, 1):
        print(f"\n--- 文档 {i} ---")
        print(f"内容预览: {doc.page_content[:80]}...")
        print(f"Metadata: doc_category={doc.metadata.get('doc_category', 'N/A')}")


if __name__ == "__main__":
    # 运行所有测试
    test_scheme()
    test_mmr()
    test_metadata_filter()

    print("\n" + "=" * 60)
    print("✅ 所有测试完成！")
    print("=" * 60)
