## Task 3.1 多查询检索器（MultiQueryRetriever）

### 任务目标
实现 MultiQueryRetriever，通过 LLM 生成多个角度的查询变体分别检索并合并结果，提升模糊问题和多义词问题的召回率。

### 涉及文件
- `src/retrieval/multi_query.py`
- `src/workflow/nodes.py`（修改检索节点支持策略切换）

### 面试级知识点
- **MultiQuery 的核心原理**：传统向量检索依赖单一查询 embedding，当用户问题模糊、多义或跨多个领域时，单一查询难以覆盖所有相关文档。MultiQuery 使用 LLM 从不同角度生成 3-5 个查询变体，每个变体独立检索后去重合并，形成更丰富的候选集。
- **RAG 开发的 6 阶段优化模型**：查询转换（含 MultiQuery、HyDE、RAG Fusion）、路由、查询构建、索引、检索、生成——理解每个阶段对应的优化策略是面试高频考点。
- **MultiQuery vs RAG Fusion 的区别**：MultiQuery 生成语义不同的查询变体；RAG Fusion 在 MultiQuery 基础上引入倒数排名融合（RRF）算法重新排序合并结果。

### 生产级注意事项
- **查询变体数量权衡**：生成 3 个变体是业界常用平衡点——太少（2 个）覆盖面不足，太多（5+ 个）显著增加 LLM 调用成本和延迟。可在配置文件中设置 `multi_query_count=3`，评估时对比不同数量的收益。
- **去重策略**：不同变体可能检索到相同文档，使用文档 ID（或 `source` + `page_content` 前 100 字符的哈希）去重，避免 LLM 重复处理相同上下文。
- **并行检索**：使用 `asyncio.gather` 并发执行多个变体的检索请求，将总体延迟控制在单次检索的 1.2-1.5 倍内，而非线性累加。
- **缓存查询变体生成**：相同问题重复调用时，LLM 生成的变体应缓存，避免重复消耗 token。使用 `functools.lru_cache` 或 Phase 4 的语义缓存。
- **Prompt 设计**：MultiQuery 的 Prompt 应明确要求生成"语义不同、角度互补"的变体，避免生成同义反复。示例：`"Generate 3 different rephrasings of the following question, each capturing a distinct aspect or perspective."`

### 验收标准
- 运行 Phase 1 的检索评估脚本，对比 `BaseRetriever` 和 `MultiQueryRetriever` 在 20 个 QA pairs 上的 Hit Rate@5、MRR@5、NDCG@5。
- MultiQuery 的 Hit Rate@5 相比 Baseline 至少提升 10%（若无提升，需分析原因并记录在评估报告中）。
- 检查去重逻辑：用相同问题调用两次，日志中显示变体生成被缓存命中，实际 LLM 调用次数仅为 1 次。
- 手动测试一个模糊问题（如"LangChain 的 chain 怎么用"），观察检索结果是否覆盖了不同类型的 chain（LLMChain、SequentialChain、RouterChain）。
