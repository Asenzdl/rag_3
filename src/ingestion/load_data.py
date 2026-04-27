"""数据入库编排脚本 — 加载 → 合并 metadata → 切分 → 入库。

调用 ingestion 包中的各模块完成完整 pipeline。
"""

from pathlib import Path
from typing import List

# 注意：使用相对导入避免循环导入
# from src.ingestion import ... 会导致循环，因为 __init__.py 会导入本模块
from .loader import (
    load_directory,
    load_metadata_index,
    enrich_docs_with_index,
)
from .splitter import SmartDocumentSplitter
from .vectorstore import ingest_to_chroma


# ============================================================
# 默认配置
# ============================================================
DATA_DIR = [
    "data/langchain_docs_separated/oss/python/langchain",
    "data/langchain_docs_separated/oss/python/langgraph",
]
EXCLUDE_DIRS = ["frontend"]


def run_pipeline(
    data_dir: str | List[str] = DATA_DIR,
    exclude_dirs: List[str] = EXCLUDE_DIRS,
    metadata_json: str = "data/langchain_docs_separated/metadata_index.json",
    persist_dir: str = "db/langchain_docs_db1",
    collection_name: str = "langchain_docs1",
):
    """完整流水线：加载 -> 合并 metadata -> 切分 -> 入库。"""
    # 1. 加载文档（解析 frontmatter）
    print("[1/4] 加载 Markdown 文档...")
    docs = load_directory(data_dir, exclude_dirs=exclude_dirs)
    print(f"  共加载 {len(docs)} 篇文档")

    # 2. 整合 metadata_index.json
    print("[2/4] 整合 metadata_index.json...")
    index = load_metadata_index(metadata_json)
    # 用 metadata_json 所在目录作为基准路径（多目录时 data_dir 是列表）
    index_base_dir = str(Path(metadata_json).parent)
    docs = enrich_docs_with_index(docs, index, index_base_dir)

    # 3. 切分
    print("[3/4] 智能切分...")
    splitter = SmartDocumentSplitter(chunk_size=2000, chunk_overlap=200)
    chunks = splitter.smart_split(docs)
    print(f"  共产出 {len(chunks)} 个 chunks")

    # 4. 入库
    print("[4/4] 存入 Chroma...")
    vectorstore = ingest_to_chroma(
        chunks,
        persist_directory=persist_dir,
        collection_name=collection_name,
    )
    return vectorstore


if __name__ == "__main__":
    run_pipeline()
