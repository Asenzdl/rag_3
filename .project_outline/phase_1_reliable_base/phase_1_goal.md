# Phase 1：可靠基座 + 评估驱动

总目标：完成一个端到端可运行、可评估、可追溯的基础 RAG 问答系统，并建立后续迭代的量化基线。


## Phase 1 完成后的交付物清单
- 可执行程序：python src/app.py 启动交互式问答。

- 评估基线报告：data/eval/baseline_retrieval_report.md，记录当前切分策略下的 Hit Rate、MRR、NDCG。

- 单元测试：tests/test_metrics.py 覆盖指标计算逻辑。

- 端到端测试：tests/test_e2e.py 验证核心链路。

- 日志文件：logs/app.log 包含结构化 JSON 日志。