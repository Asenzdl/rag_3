## Task 3.6 A/B 对比工具与检索策略横评

### 任务目标
开发统一的 A/B 对比工具，支持对任意两种检索策略（或系统配置）进行横向对比，输出可视化对比报告，为策略选择提供数据支撑。

### 涉及文件
- `src/evaluation/compare.py`
- `src/evaluation/report_generator.py`

### 面试级知识点
- **A/B 测试在 RAG 系统中的应用**：传统 A/B 测试需要线上流量分流，RAG 系统的 A/B 测试可通过离线评估数据集完成——同一批问题分别喂给两个系统配置，对比输出质量。离线评估成本低、可重复、不受用户流量影响。
- **统计显著性检验**：两个策略的指标差异是否具有统计意义？对于离线评估数据集，可使用配对 t 检验或 Bootstrap 重采样判断差异是否显著。
- **评估指标的选择性汇报**：面试时强调"不能只看一个指标"——Hit Rate 提升 10% 但 Answer Relevancy 下降 5%，需要综合权衡。

### 生产级注意事项
- **对比工具的模块化设计**：
  ```python
  class CompareRunner:
      def __init__(self, config_a: SystemConfig, config_b: SystemConfig): ...
      def run_comparison(self, dataset: List[EvalSample]) -> CompareReport: ...
      def generate_markdown(self, report: CompareReport) -> str: ...
  ```
- **对比维度**：检索指标（Hit Rate@3/5、MRR@3/5、NDCG@3/5）、生成指标（Faithfulness、Answer Relevancy）、性能指标（平均延迟、Token 消耗）。
- **报告格式**：Markdown 表格 + 雷达图（6 维指标可视化）。雷达图可借助 `matplotlib` 生成 PNG，嵌入 Markdown 报告中。
- **对比结果的版本管理**：每次对比生成 `compare_{strategy_a}_vs_{strategy_b}_{date}.md`，纳入 `data/eval/reports/` 目录并提交 Git，形成可追溯的优化历史。

### 验收标准
- 运行 `python src/evaluation/compare.py --base base --target multi_query`，输出一份对比报告。
- 报告包含：两个策略在 4 项 RAGAS 指标 + 3 项检索指标上的数值对比、差异百分比、胜负总结。
- 使用 Phase 1 的手工 QA pairs 和 Phase 3.5 的 RAGAS 测试集分别跑对比，验证结论一致性。
- 报告中生成雷达图，直观展示多维度差异。
- 基于对比结果，在项目文档（`AGENTS.md`）中记录"最终选用的检索策略"及其决策依据。
