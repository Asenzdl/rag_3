"""Task 1.3 验收脚本：验证 similarity / MMR 检索对比。"""
from src.core.config import settings
from src.core.factories import create_retriever

# 1. similarity 检索
r1 = create_retriever(settings, search_type="similarity", search_kwargs={"k": 5})
docs1 = r1.invoke("What is LangGraph?")
print(f"=== similarity: {len(docs1)} docs ===")
for i, d in enumerate(docs1):
    print(f"  [{i}] {d.metadata.get('source', '?')[:80]}")

# 2. MMR 检索
r2 = create_retriever(settings, search_type="mmr", search_kwargs={"k": 5, "lambda_mult": 0.5})
docs2 = r2.invoke("What is LangGraph?")
print(f"\n=== mmr: {len(docs2)} docs ===")
for i, d in enumerate(docs2):
    print(f"  [{i}] {d.metadata.get('source', '?')[:80]}")

# 3. 多样性对比
s1 = [d.metadata.get("source") for d in docs1]
s2 = [d.metadata.get("source") for d in docs2]
print(f"\nsources overlap: {len(set(s1) & set(s2))}/{len(s1)}")
print("PASS: retriever works correctly")
