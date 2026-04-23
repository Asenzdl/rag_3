from src.ingestion import SmartDocumentSplitter, load_markdown_with_frontmatter

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
