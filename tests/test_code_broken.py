"""代码块完整性验证脚本 — 检查文档切分后代码块是否被截断。

注意：这是开发验证脚本，不是正式测试用例。
用于验证 SmartDocumentSplitter 的代码块保护功能。
"""

# SmartDocumentSplitter 是公共 API，从包级别导入
from src.ingestion import SmartDocumentSplitter

# load_markdown_with_frontmatter 是内部工具，需要从子模块显式导入
from src.ingestion.loader import load_markdown_with_frontmatter

doc = load_markdown_with_frontmatter("data/langchain_docs_separated/oss/python/langchain/human-in-the-loop.md")
splitter = SmartDocumentSplitter(chunk_size=1300, chunk_overlap=130)
chunks = splitter.smart_split([doc])

broken_count = 0
# 检查：代码块是否完整
for i, c in enumerate(chunks):
    open_count = c.page_content.count("```")
    if open_count % 2 != 0:
        broken_count += 1
    print(f"chunk[{i}] len={len(c.page_content)} code_blocks={'OK' if open_count % 2 == 0 else 'BROKEN'}")
    print(f"  metadata: h1={c.metadata.get('h1','')}, h2={c.metadata.get('h2','')}")

print(f"broken_count={broken_count}")
