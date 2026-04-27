## Task 1.1 切分策略优化与向量库重建

### 任务目标
根据文档特征优化分块策略，重建 Chroma 向量库，确保每个 chunk 包含完整的"说明+代码"逻辑单元。

### 涉及文件
- `src/ingestion/load_data.py`
- `src/ingestion/splitter.py`

### 面试级知识点
- **Markdown 感知切分**：为何不能直接用 `RecursiveCharacterTextSplitter`？代码块被切断会导致检索结果不完整。
- **Chunk Size 的权衡**：太大导致检索精度下降（噪声增加），太小导致上下文缺失（召回率下降）。
- **Metadata 策略**：标题层级、文档来源 URL 作为元数据存储，用于后续引用和过滤。

### 生产级注意事项
- **代码块保护实现**：使用正则或简单状态机识别 ` ``` ` 边界，在 `split_documents` 前将代码块替换为占位符，切分后再还原。
- **切分可重现性**：通过配置文件控制 `chunk_size`、`chunk_overlap`、`headers_to_split_on`，避免硬编码。
- **向量库版本管理**：在 `db/` 目录下保留 `metadata.json` 记录入库时间、切分参数、文档数量，便于回溯。

### 验收标准
- 运行 `load_data.py` 后，随机抽样 10 个 chunk，人工检查每个 chunk 中的代码块是否完整（无截断）。
- 向量库中的文档数量与 Markdown 拆分预期数量偏差 < 5%。
- 使用简单查询（如 "How to create a tool in LangChain?"）检索，返回的 top-3 文档中至少有一个包含完整代码示例。
