## Task 3.4 重排序器（Reranker：Cohere / Cross-Encoder）

### 任务目标
在检索后增加重排序层，使用 Cross-Encoder 模型（Cohere Rerank 或本地 Sentence-Transformer）对候选文档进行精细排序，筛选出与查询最相关的前 K 个文档输入 LLM，提升答案质量。

### 涉及文件
- `src/retrieval/reranker.py`
- `src/workflow/nodes.py`（在 `retrieve` 和 `generate` 之间插入 `rerank` 节点）

### 面试级知识点
- **Bi-Encoder vs Cross-Encoder**：Bi-Encoder（如 Embedding 模型）分别编码查询和文档，通过余弦相似度计算相关性——速度快但精度有限。Cross-Encoder 将查询和文档拼接后一起编码，直接输出相关性分数——精度高但计算量大，适合对少量候选文档重排序。
- **Reranker 在 RAG 中的定位**：作为"精排层"，从粗排（向量检索/B25）返回的 20-50 个候选中精选出 3-5 个最相关的输入 LLM。这与推荐系统中的"召回→粗排→精排"架构一脉相承。
- **Cohere Rerank vs 本地 Cross-Encoder**：Cohere Rerank 是商业 API，效果好、免部署，但有网络延迟和成本；本地 Cross-Encoder（如 `cross-encoder/ms-marco-MiniLM-L-6-v2`）免费、低延迟，但效果略逊于商业模型。面试时要能说出权衡。

### 生产级注意事项
- **ContextualCompressionRetriever 封装**：LangChain 提供 `ContextualCompressionRetriever`，将 `base_retriever` 和 `base_compressor`（Reranker）组合，自动完成"检索 → 重排序 → 压缩"流程。
- **Reranker 的 batch 调用**：将多个候选文档一次性发送给 Reranker API（而非逐个调用），显著降低网络往返次数。Cohere Rerank API 支持单次请求最多 1000 个文档。
- **延迟与成本的权衡**：Reranker 增加 200-500ms 延迟和 API 成本。建议配置开关，仅在文档评估节点判定"相关"后启用，或在 `top_k > 10` 时触发压缩。
- **本地 Reranker 的选型**：若选择本地部署，推荐 `BAAI/bge-reranker-base` 或 `ms-marco-MiniLM-L-6-v2`，在 CPU 上推理延迟约 50-100ms/对。
- **Reranker 结果缓存**：相同 `(query, doc_id)` 对的重排序分数可缓存（如 Redis），避免重复计算。

### 验收标准
- 实现 `RerankerCompressor` 类，支持 Cohere Rerank API 和本地 Cross-Encoder 两种模式，通过环境变量切换。
- 在 LangGraph 工作流中增加 `rerank` 节点（位于 `retrieve` 之后、`grade_documents` 之前），候选文档从 20 个压缩至 5 个。
- 运行评估脚本，对比"有 Reranker"和"无 Reranker"两种配置下的生成质量（LLM-as-Judge faithfulness 评分）。
- 记录 Reranker 引入后的延迟增量，确保单次请求增加 ≤ 500ms。
- 编写单元测试验证 Reranker 的降级逻辑：API 不可用时自动跳过 Rerank 步骤，不阻断主流程。
