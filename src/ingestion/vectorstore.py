"""向量库入库模块。

职责：
- 将切分后的 Document chunks 存入 Chroma 向量库
- 清洗 metadata 类型（Chroma 仅支持 str/int/float/bool）
"""

from typing import List

from langchain_core.documents import Document

from langchain_chroma import Chroma
from src.core.config import ollama_embeddings


def ingest_to_chroma(
    chunks: List[Document],
    persist_directory: str = "db/langchain_docs_db",
    collection_name: str = "langchain_docs",
):
    """将带完整 metadata 的 chunks 存入 Chroma 向量库。"""
    
    # Chroma metadata 只支持 str / int / float / bool，需清洗
    for chunk in chunks:
        for k, v in list(chunk.metadata.items()):
            if v is None:
                chunk.metadata[k] = ""
            elif not isinstance(v, (str, int, float, bool)):
                chunk.metadata[k] = str(v)

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=ollama_embeddings,
        persist_directory=persist_directory,
        collection_name=collection_name,
    )
    print(f"[INFO] 已存入 {len(chunks)} 个 chunks 到 {persist_directory}")
    return vectorstore
