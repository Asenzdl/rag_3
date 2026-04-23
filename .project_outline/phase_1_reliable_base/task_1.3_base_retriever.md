## Task 1.3 基础向量检索器封装

### 任务目标
封装 Chroma 向量存储，提供统一的检索接口，支持相似度检索和 MMR 去重。

### 涉及文件
- `src/retrieval/base_retriever.py`

### 面试级知识点
- **VectorStore vs Retriever**：LangChain 中两者的区别与使用场景。
- **MMR (Maximum Marginal Relevance)** 原理：平衡查询相关性与文档间多样性，`lambda_mult` 参数调优。
- **Metadata 过滤**：如何利用元数据（如 `doc_category`）缩小检索范围，提升精度。

### 生产级注意事项
- **单例模式或依赖注入**：`BaseRetriever` 应接收已初始化的 `VectorStore` 对象，避免每次检索都重新加载向量库。
- **top_k 可配置**：默认值（如 6）通过配置文件控制，评估时便于调整。
- **检索结果标准化**：返回 `List[Document]`，每个 `Document` 必须包含 `page_content` 和 `metadata`（至少含 `source`、`title`）。
- **异常处理**：向量库连接失败时抛出明确的自定义异常（`RetrievalError`），而非裸 RuntimeError。

### 验收标准
- 使用 Task 1.2 数据集中的一个问题调用 `retrieve()`，返回文档数量等于 `top_k`（除非库中总数不足）。
- 打印返回的每个文档的 `source` 字段，验证其格式为有效 URL。
- 对比 `search_type="similarity"` 和 `search_type="mmr"` 的返回结果，观察多样性差异。
