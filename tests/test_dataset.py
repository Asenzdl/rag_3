"""dataset.py 单元测试。

覆盖场景：
1. 缺少字段时 logger.warning 被调用
2. 合法数据正确加载
3. 文件不存在时 FileNotFoundError
4. print_dataset_stats 使用 print 而非 logger
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.evaluation.dataset import EvalSample, load_eval_dataset, print_dataset_stats


# ============================================================
# 测试数据
# ============================================================

VALID_ENTRIES = [
    {
        "id": "q001",
        "question": "LangGraph 是什么？",
        "expected_sources": ["https://example.com/1"],
        "category": "rag",
        "difficulty": "easy",
    },
    {
        "id": "q002",
        "question": "StateGraph 怎么用？",
        "expected_sources": ["https://example.com/2"],
        "category": "agents",
        "difficulty": "medium",
    },
]

ENTRY_MISSING_FIELD = [
    {
        "id": "q001",
        "question": "LangGraph 是什么？",
        # 缺少 expected_sources
        "category": "rag",
        "difficulty": "easy",
    },
]


# ============================================================
# load_eval_dataset 测试
# ============================================================


class TestLoadEvalDataset:
    """load_eval_dataset 函数测试。"""

    def test_load_eval_dataset_valid_data(self, tmp_path):
        """合法 JSON 数据正确加载。"""
        json_path = tmp_path / "test_qa.json"
        json_path.write_text(json.dumps(VALID_ENTRIES, ensure_ascii=False), encoding="utf-8")

        samples = load_eval_dataset(str(json_path))

        assert len(samples) == 2
        assert isinstance(samples[0], EvalSample)
        assert samples[0].id == "q001"
        assert samples[0].question == "LangGraph 是什么？"
        assert samples[1].expected_sources == ["https://example.com/2"]

    def test_load_eval_dataset_missing_field_logs_warning(self, tmp_path):
        """缺少字段时样本被跳过 + logger.warning 被调用。"""
        json_path = tmp_path / "test_qa.json"
        json_path.write_text(json.dumps(ENTRY_MISSING_FIELD, ensure_ascii=False), encoding="utf-8")

        with patch("src.evaluation.dataset.logger") as mock_logger:
            samples = load_eval_dataset(str(json_path))

        # 缺少 expected_sources 的样本应被跳过
        assert len(samples) == 0
        # logger.warning 应被调用
        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args
        assert call_kwargs[1]["index"] == 0
        assert "expected_sources" in call_kwargs[1]["missing_field"]

    def test_load_eval_dataset_file_not_found(self):
        """文件不存在时抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError, match="评估数据集文件不存在"):
            load_eval_dataset("/nonexistent/path/qa_pairs.json")


# ============================================================
# print_dataset_stats 测试
# ============================================================


class TestPrintDatasetStats:
    """print_dataset_stats 函数测试。"""

    def test_print_dataset_stats_uses_print(self):
        """print_dataset_stats 调用 print 而非 logger。"""
        samples = [
            EvalSample(
                id="q001",
                question="测试",
                expected_sources=["https://example.com/1"],
                category="rag",
                difficulty="easy",
            ),
        ]

        with patch("builtins.print") as mock_print, \
             patch("src.evaluation.dataset.logger") as mock_logger:
            print_dataset_stats(samples)

        # print 应被多次调用（统计输出）
        assert mock_print.call_count > 0
        # logger 不应被调用
        mock_logger.warning.assert_not_called()
        mock_logger.info.assert_not_called()
