## Task 1.2 评估数据集构建

### 任务目标
建立手工标注的评估数据集（QA Pairs），覆盖不同文档类别，用于检索和生成评估。

### 涉及文件
- `data/eval/qa_pairs.json`
- `src/evaluation/dataset.py`

### 面试级知识点
- **评估数据集设计原则**：问题多样性（概念类、操作类、代码类）、答案来源明确（标注预期命中的 source URL）。
- **Golden Dataset 的作用**：离线评估是迭代检索策略的唯一可信依据，避免"感觉变好了"的主观判断。

### 生产级注意事项
- **QA Pair 格式规范**：
  ```json
  {
    "id": "q001",
    "question": "如何在 LangChain 中给 Agent 添加记忆？",
    "expected_sources": ["https://docs.langchain.com/...", ...],
    "relevant_doc_ids": ["chunk_uuid_1", "chunk_uuid_2"],
    "category": "memory"
  }
  ```
- **版本控制**：`qa_pairs.json` 纳入 Git，每次修改需在 commit message 中说明原因。
- **数据集加载器**：`dataset.py` 提供 `load_eval_dataset()` 函数，返回标准化的 `List[EvalSample]` 对象。

### 验收标准
- 数据集至少包含 25 个 QA pairs，覆盖 `agents`、`chains`、`memory`、`tools` 四个类别。
- 每个 QA pair 的 `expected_sources` 字段非空且指向真实存在的文档 URL。
- 运行 `python src/evaluation/dataset.py` 能正确加载并打印数据集统计信息。
