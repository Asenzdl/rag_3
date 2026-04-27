"""evaluation 包 — 评估数据集与评估指标的统一入口。

⚠️ 注意：这是离线评估工具，不是生产 API。
重构其他模块时，请跳过本模块。

公共 API：
    - 数据集：EvalSample, load_eval_dataset
    - 指标函数：hit_rate_at_k, mrr_at_k, ndcg_at_k
    - 评估器：RetrievalEvaluator, run_baseline_eval
    - 数据类：QueryEvalResult, EvalReport
    - 匹配策略：SourceMatcher, ExactSourceMatcher

内部工具（不导出）：
    - print_dataset_stats: 调试辅助函数（仅 CLI 使用）
"""

from .dataset import EvalSample, load_eval_dataset
from .metrics import hit_rate_at_k, mrr_at_k, ndcg_at_k
from .retrieval_eval import (
    ExactSourceMatcher,
    EvalReport,
    QueryEvalResult,
    RetrievalEvaluator,
    SourceMatcher,
    run_baseline_eval,
)

__all__ = [
    # 数据集
    "EvalSample",
    "load_eval_dataset",
    # 评估指标
    "hit_rate_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    # 评估器与报告
    "RetrievalEvaluator",
    "run_baseline_eval",
    "QueryEvalResult",
    "EvalReport",
    # 匹配策略
    "SourceMatcher",
    "ExactSourceMatcher",
]
