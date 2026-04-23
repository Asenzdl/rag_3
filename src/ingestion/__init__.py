"""ingestion 包 — 文档加载、切分、入库的统一入口。

Usage:
    from ingestion import load_directory, SmartDocumentSplitter, ingest_to_chroma
"""

from .loader import (
    load_directory,
    load_markdown_with_frontmatter,
    load_metadata_index,
    enrich_docs_with_index,
)

from .load_data import run_pipeline
from .splitter import SmartDocumentSplitter
from .vectorstore import ingest_to_chroma

__all__ = [
    "run_pipeline", 
    "load_directory",
    "load_markdown_with_frontmatter",
    "load_metadata_index",
    "enrich_docs_with_index",
    "SmartDocumentSplitter",
    "ingest_to_chroma",
]
