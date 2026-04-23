"""检索评估指标计算模块（纯 Python，零外部依赖）。

三个核心指标：
- Hit Rate@k：前 k 个结果中是否包含至少一个相关文档（二值，对排名不敏感）
- MRR@k：第一个相关文档的排名倒数（关注"第一个正确答案的位置"）
- NDCG@k：归一化折损累积增益（考虑多级相关性 + 排名加权）

设计原则：
- 仅依赖 List[str] 标准数据结构，与 LangChain/LangGraph 完全解耦
- 边界安全：relevant_ids 为空时统一返回 0.0
- 可扩展：NDCG 当前二值相关性，注释中说明如何扩展到分级

面试要点：
- Hit Rate 回答"有没有"，MRR 回答"第一个正确在哪"，NDCG 回答"整体排序好不好"
- NDCG 的 IDCG 是理想排序的 DCG，归一化保证值域 [0, 1] 可跨场景比较
"""

import math
from typing import List


def hit_rate_at_k(
    retrieved_ids: List[str],
    relevant_ids: List[str],
    k: int = 3,
) -> float:
    """计算 Hit Rate@k：前 k 个检索结果中是否包含至少一个相关文档。

    值域：{0.0, 1.0}，简单直观但对排名不敏感。
    适用场景：快速验证"有没有"。

    Args:
        retrieved_ids: 检索返回的文档 ID 列表（按排名顺序，位置 0 = 排名第 1）。
        relevant_ids: 相关文档 ID 列表（ground truth）。
        k: 截断位置。

    Returns:
        1.0 如果前 k 个结果中包含至少一个相关文档，否则 0.0。
        当 relevant_ids 为空时返回 0.0。
    """
    if not relevant_ids:
        return 0.0

    top_k = set(retrieved_ids[:k])
    relevant_set = set(relevant_ids)
    return 1.0 if top_k & relevant_set else 0.0


def mrr_at_k(
    retrieved_ids: List[str],
    relevant_ids: List[str],
    k: int = 3,
) -> float:
    """计算 MRR@k（Mean Reciprocal Rank）：第一个相关文档的排名倒数。

    值域：(0.0, 1.0]，1.0 = 第一个结果就命中。
    适用场景：优化"第一个正确答案的位置"（如 FAQ、单答案检索）。

    Args:
        retrieved_ids: 检索返回的文档 ID 列表（按排名顺序）。
        relevant_ids: 相关文档 ID 列表。
        k: 截断位置。

    Returns:
        1/rank（rank 从 1 开始），前 k 个无相关文档返回 0.0。
        当 relevant_ids 为空时返回 0.0。
    """
    if not relevant_ids:
        return 0.0

    relevant_set = set(relevant_ids)
    for i, doc_id in enumerate(retrieved_ids[:k]):
        if doc_id in relevant_set:
            return 1.0 / (i + 1)
    return 0.0


def _dcg_at_k(relevance_scores: List[float], k: int) -> float:
    """计算 DCG@k（Discounted Cumulative Gain）。

    公式：DCG@k = Σ(i=1 to k) rel_i / log2(i + 1)
    其中 i 从 1 开始（排名位置），rel_i 是位置 i 的相关性分数。

    这是内部辅助函数，不对外导出。

    Args:
        relevance_scores: 按排名顺序的相关性分数列表。
        k: 截断位置。

    Returns:
        DCG@k 值。
    """
    dcg = 0.0
    for i, score in enumerate(relevance_scores[:k]):
        # i 从 0 开始索引 → 排名位置 = i + 1 → 折损因子 = log2(i + 1 + 1) = log2(i + 2)
        dcg += score / math.log2(i + 2)
    return dcg


def ndcg_at_k(
    retrieved_ids: List[str],
    relevant_ids: List[str],
    k: int = 3,
) -> float:
    """计算 NDCG@k（Normalized Discounted Cumulative Gain）。

    值域：[0.0, 1.0]，1.0 = 完美排序。
    适用场景：精细排名场景，需要区分"第 1 位 vs 第 3 位命中"的差异。

    当前使用二值相关性（相关=1，不相关=0）。
    扩展到分级相关性时，将 relevant_ids: List[str] 替换为
    relevance_map: Dict[str, float]，并修改 rel_score 计算逻辑：
      rel_score = relevance_map.get(doc_id, 0.0)

    Args:
        retrieved_ids: 检索返回的文档 ID 列表（按排名顺序）。
        relevant_ids: 相关文档 ID 列表。
        k: 截断位置。

    Returns:
        NDCG@k 值，范围 [0.0, 1.0]。
        当 relevant_ids 为空时返回 0.0。
    """
    if not relevant_ids:
        return 0.0

    relevant_set = set(relevant_ids)

    # 实际相关性分数（二值：1.0 if in relevant else 0.0）
    actual_scores = [
        1.0 if doc_id in relevant_set else 0.0
        for doc_id in retrieved_ids
    ]
    dcg = _dcg_at_k(actual_scores, k)

    # 理想相关性分数：所有相关文档排在最前
    ideal_scores = [1.0] * min(len(relevant_ids), k)
    idcg = _dcg_at_k(ideal_scores, k)

    if idcg == 0.0:
        return 0.0

    return dcg / idcg
