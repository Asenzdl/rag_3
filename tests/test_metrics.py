"""检索评估指标单元测试。

验证策略：用已知输入/输出对测试，确保指标计算的数学正确性。
覆盖：正常情况 + 边界情况（空列表、超出 k、多相关文档）。
"""

import math
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.evaluation.metrics import hit_rate_at_k, mrr_at_k, ndcg_at_k


# ============================================================
# Hit Rate@k 测试
# ============================================================

class TestHitRate:

    def test_found_in_top_k(self):
        """正常命中：相关文档在 top-k 内。"""
        assert hit_rate_at_k(["d1", "d2", "d3"], ["d2"], k=3) == 1.0

    def test_not_found(self):
        """相关文档不在 top-k 内。"""
        assert hit_rate_at_k(["d1", "d3", "d4"], ["d2"], k=3) == 0.0

    def test_found_beyond_k(self):
        """相关文档存在但超出 k（排名第 4，k=3）。"""
        assert hit_rate_at_k(["d1", "d3", "d4", "d2"], ["d2"], k=3) == 0.0

    def test_empty_relevant(self):
        """边界：relevant_ids 为空 → 0.0。"""
        assert hit_rate_at_k(["d1", "d2"], [], k=3) == 0.0

    def test_empty_retrieved(self):
        """边界：retrieved_ids 为空 → 0.0。"""
        assert hit_rate_at_k([], ["d1"], k=3) == 0.0

    def test_both_empty(self):
        """边界：两者都为空 → 0.0。"""
        assert hit_rate_at_k([], [], k=3) == 0.0

    def test_k_larger_than_retrieved(self):
        """k 大于检索结果数量，但仍有命中。"""
        assert hit_rate_at_k(["d1"], ["d1"], k=5) == 1.0


# ============================================================
# MRR@k 测试
# ============================================================

class TestMRR:

    def test_first_position(self):
        """第 1 位命中 → 1/1 = 1.0。"""
        assert mrr_at_k(["d1", "d2", "d3"], ["d1"], k=3) == 1.0

    def test_second_position(self):
        """第 2 位命中 → 1/2 = 0.5。"""
        assert mrr_at_k(["d1", "d2", "d3"], ["d2"], k=3) == 0.5

    def test_third_position(self):
        """第 3 位命中 → 1/3 ≈ 0.3333。"""
        result = mrr_at_k(["d1", "d2", "d3"], ["d3"], k=3)
        assert abs(result - 1.0 / 3) < 1e-6

    def test_not_in_top_k(self):
        """超出 k → 0.0。"""
        assert mrr_at_k(["d1", "d3", "d4", "d2"], ["d2"], k=3) == 0.0

    def test_empty_relevant(self):
        """边界：relevant_ids 为空 → 0.0。"""
        assert mrr_at_k(["d1", "d2"], [], k=3) == 0.0

    def test_empty_retrieved(self):
        """边界：retrieved_ids 为空 → 0.0。"""
        assert mrr_at_k([], ["d1"], k=3) == 0.0

    def test_multiple_relevant_takes_first(self):
        """多个 relevant，MRR 只看第一个命中的位置。"""
        # d1 在位置 1 → 第一个命中 → 1/1 = 1.0
        assert mrr_at_k(["d1", "d2", "d3"], ["d1", "d2"], k=3) == 1.0

    def test_multiple_relevant_second_hit(self):
        """多个 relevant，第一个命中在位置 2。"""
        # d2 在位置 2 是第一个命中 → 1/2 = 0.5
        assert mrr_at_k(["d3", "d2", "d1"], ["d1", "d2"], k=3) == 0.5


# ============================================================
# NDCG@k 测试
# ============================================================

class TestNDCG:

    def test_perfect_ranking(self):
        """完美排序：相关文档排在第 1 位 → 1.0。"""
        assert ndcg_at_k(["d1", "d2", "d3"], ["d1"], k=3) == 1.0

    def test_second_position(self):
        """相关文档排在第 2 位。
        DCG = 0/log2(2) + 1/log2(3) ≈ 0.6309
        IDCG = 1/log2(2) = 1.0
        NDCG ≈ 0.6309
        """
        result = ndcg_at_k(["d1", "d2", "d3"], ["d2"], k=3)
        expected = 1.0 / math.log2(3)
        assert abs(result - expected) < 1e-6

    def test_no_relevant(self):
        """无相关文档 → 0.0。"""
        assert ndcg_at_k(["d1", "d3", "d5"], ["d2"], k=3) == 0.0

    def test_multiple_relevant_perfect(self):
        """多个相关文档全部排在最前 → 1.0。"""
        assert ndcg_at_k(["d1", "d2", "d3"], ["d1", "d2"], k=3) == 1.0

    def test_empty_relevant(self):
        """边界：relevant_ids 为空 → 0.0。"""
        assert ndcg_at_k(["d1", "d2"], [], k=3) == 0.0

    def test_empty_retrieved(self):
        """边界：retrieved_ids 为空 → 0.0。"""
        assert ndcg_at_k([], ["d1"], k=3) == 0.0

    def test_multiple_relevant_imperfect(self):
        """多个相关文档排序不完美 → 0 < NDCG < 1。"""
        # retrieved=["d3","d2","d1"], relevant=["d1","d2"]
        # rel_scores = [0, 1, 1]
        # DCG = 0 + 1/log2(3) + 1/log2(4)
        # IDCG = 1/log2(2) + 1/log2(3) (2个相关，k=3)
        result = ndcg_at_k(["d3", "d2", "d1"], ["d1", "d2"], k=3)
        assert 0.0 < result < 1.0

    def test_all_relevant_beyond_k(self):
        """所有相关文档都超出 k → 0.0。"""
        assert ndcg_at_k(["d4", "d5", "d6"], ["d1", "d2", "d3"], k=3) == 0.0

    def test_k_larger_than_relevant_count(self):
        """k 大于相关文档数量时，IDCG 只计算实际相关数。"""
        # 1 个相关文档排在第 1 位 → NDCG = 1.0
        assert ndcg_at_k(["d1", "d2", "d3"], ["d1"], k=10) == 1.0
