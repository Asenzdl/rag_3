# Phase 3：评估驱动检索增强

总目标：基于 Phase 1 建立的评估基线和 Phase 2 构建的 LangGraph 骨架，逐个引入高级检索策略（MultiQuery、HyDE、Ensemble、Reranker），通过 A/B 对比数据驱动决策，并通过 RAGAS 框架建立完整的生成质量评估体系。

核心原则：每增加一种检索策略，立即跑一次评估对比，数据驱动决策，拒绝“感觉变好了”的主观判断。

## Phase 3 完成后的交付物清单
- 四种高级检索器实现：multi_query.py、hyde.py、ensemble.py、reranker.py，均可通过工厂函数配置切换。
- RAGAS 评估集成：ragas_eval.py 和自动生成的 50+ 条评估测试集。
- A/B 对比工具：compare.py 支持任意策略横向对比，输出 Markdown + 雷达图报告。
- 策略决策文档：docs/retrieval_strategy_decision.md，记录数据驱动的架构决策。
- 评估报告集合：data/eval/reports/ 下保存历次对比报告，形成可追溯的优化历史。
- 可配置的检索架构：通过环境变量切换检索策略，无需修改代码。
