"""evaluation 包 — 评估数据集与评估指标的统一入口。"""

from .dataset import EvalSample, load_eval_dataset, print_dataset_stats
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
    # dataset
    "EvalSample",
    "load_eval_dataset",
    "print_dataset_stats",
    # metrics
    "hit_rate_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    # retrieval_eval
    "ExactSourceMatcher",
    "EvalReport",
    "QueryEvalResult",
    "RetrievalEvaluator",
    "SourceMatcher",
    "run_baseline_eval",
]
