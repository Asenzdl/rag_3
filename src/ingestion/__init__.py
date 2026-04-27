"""ingestion 包 — 文档加载、切分、入库的统一入口。

⚠️ 注意：这是离线数据预处理管道，不是实时 API。
重构其他模块时，请跳过本模块。

核心 API：
    - run_pipeline: 一键完成加载 → 切分 → 入库（推荐）
    - SmartDocumentSplitter: 文档切分器（可调参测试）
    - ingest_to_chroma: 向量库入库（可单独使用）

内部工具（不导出，需显式导入子模块）：
    - loader.load_directory: 文档加载
    - loader.load_markdown_with_frontmatter: 单文件加载
    - loader.load_metadata_index: JSON 加载
    - loader.enrich_docs_with_index: metadata 合并

使用示例：
    # 推荐：完整流水线
    from src.ingestion import run_pipeline
    run_pipeline()
    
    # 需要自定义切分参数
    from src.ingestion import SmartDocumentSplitter
    splitter = SmartDocumentSplitter(chunk_size=1500, chunk_overlap=150)
"""

# 注意：导入顺序很重要，先导入不依赖其他模块的子模块，最后导入 load_data
from .splitter import SmartDocumentSplitter
from .vectorstore import ingest_to_chroma
# load_data 依赖上面的模块，必须最后导入
from .load_data import run_pipeline

__all__ = [
    # 高层便捷接口
    "run_pipeline",
    # 可单独使用的组件
    "SmartDocumentSplitter",
    "ingest_to_chroma",
]