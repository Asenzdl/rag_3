## Task 1.4 检索评估指标实现（纯 Python，无 LLM）

### 任务目标
实现 Hit Rate@k、MRR@k、NDCG@k 三个核心检索指标，用于量化检索器性能。

### 涉及文件
- `src/evaluation/retrieval_eval.py`
- `src/evaluation/metrics.py`（指标计算独立）

### 面试级知识点
- **Hit Rate@k**：衡量前 k 个结果中是否包含至少一个相关文档。简单直观，但对排名不敏感。
- **MRR (Mean Reciprocal Rank)**：关注第一个相关文档的排名，排名越靠前分数越高。
- **NDCG (Normalized Discounted Cumulative Gain)**：考虑多级相关性打分，对排名和相关性加权。
- **何时用哪个指标**：Hit Rate 用于快速验证"有没有"，MRR 用于优化"第一个正确答案的位置"，NDCG 用于精细排名场景。

### 生产级注意事项
- **指标计算必须与 LangChain/LangGraph 解耦**：`metrics.py` 仅依赖标准数据结构（`List[str]` 检索 ID 列表，`List[str]` 相关 ID 列表），便于单元测试和复用。
- **处理边界情况**：相关文档数为 0 时，Hit Rate 为 0，MRR 为 0，NDCG 为 0（而非报错）。
- **评估报告格式**：输出 Markdown 表格，包含每个 query 的详细得分和整体平均值。

### 验收标准
- 编写单元测试（`tests/test_metrics.py`）验证指标计算的正确性（用已知输入/输出对测试）。
- 对当前向量库运行评估脚本，生成第一份 Baseline 评估报告（保存为 `data/eval/baseline_retrieval_report.md`）。
- 报告需包含：整体 Hit Rate@3、MRR@3、NDCG@3，以及按类别分组的指标。
