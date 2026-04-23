## Task 3.5 RAGAS 评估框架集成

### 任务目标
集成 RAGAS 框架，实现 RAG 系统端到端的自动化评估，覆盖检索质量（Context Precision/Recall）和生成质量（Faithfulness/Answer Relevancy）四个核心指标，建立可量化的性能基线。

### 涉及文件
- `src/evaluation/ragas_eval.py`
- `src/evaluation/ragas_metrics.py`
- `data/eval/ragas_testset.csv`

### 面试级知识点
- **RAGAS 的四项核心指标**：① Faithfulness（忠实度）——答案中的每一句话是否都能从检索到的上下文中找到依据；② Answer Relevancy（答案相关性）——答案是否紧扣问题；③ Context Precision（上下文精度）——检索到的文档中有多少是真正相关的；④ Context Recall（上下文召回率）——所有相关文档中有多少被检索到。
- **Metric-Driven Development（指标驱动开发）**：RAGAS 提出的方法论——先建立评估基线和指标，每次变更后跑评估对比，数据驱动优化。
- **RAGAS 的 LLM 依赖**：四个指标都需要调用 LLM 进行判断（通常是 GPT-4），因此评估本身有成本和延迟。面试时要能说明评估频率（每次代码变更跑完整评估，日常开发只跑采样评估）。

### 生产级注意事项
- **评估数据集的构建**：使用 RAGAS 的 `generate_testset` 从文档库自动生成评估用例（问题 + 标准答案 + 相关文档片段）。生成 50-100 条覆盖不同文档类别，人工抽样验证质量。【注意：你之前的表格中此处标注为 `llm自行判断`，现在必须替换为具体实现】
- **指标计算的具体实现**：
  ```python
  from ragas import evaluate
  from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
  
  result = evaluate(
      dataset=test_dataset,
      metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
      llm=evaluator_llm,  # 推荐 gpt-4o-mini 降本
      embeddings=embedding_model
  )
  ```
- **评估 LLM 的选择**：使用 `gpt-4o-mini` 而非 `gpt-4o` 作为评估模型，在保持评估质量的同时降低 80% 成本。需在项目中验证 mini 模型的评估结果与 4o 的相关性。
- **评估结果的可视化**：生成 Markdown 报告和 JSON 格式的原始数据，JSON 用于趋势分析，Markdown 用于人工阅读。报告应包含每个问题的详细得分和整体平均值。
- **评估频率策略**：每次 PR 合并前跑完整评估（全量测试集），开发过程中只跑 5 条采样评估（快速反馈）。

### 验收标准
- 成功安装 RAGAS（`pip install ragas`）并能在项目中导入，无依赖冲突。
- 使用 RAGAS 的 `TestsetGenerator` 从当前向量库自动生成 50 条评估用例，人工抽查 10 条验证问题质量和答案正确性。
- 对当前系统（Phase 2 的 LangGraph + BaseRetriever）运行一次完整 RAGAS 评估，生成第一份综合评估报告（保存为 `data/eval/ragas_baseline_report.md`）。
- 报告需包含：Faithfulness、Answer Relevancy、Context Precision、Context Recall 四项指标的平均值，以及按文档类别（agents/chains/memory/tools）的分组统计。
- 评估流程可重复：运行 `python src/evaluation/ragas_eval.py --config baseline` 能复现相同结果。
