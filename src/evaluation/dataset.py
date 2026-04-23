"""评估数据集加载脚本。

职责：
- 从 JSON 文件加载 QA pairs
- 提供标准化的 EvalSample 数据结构
- 打印数据集统计信息（分类分布、难度分布）
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class EvalSample:
    """单条评估样本。

    Attributes:
        id: 唯一标识，如 "q001"
        question: 中文问题
        expected_sources: 预期命中的 source URL 列表
        category: 主题分类 (rag/agents/memory/tools/graph-api/...)
        difficulty: 难度等级 (easy/medium/hard)
        relevant_doc_ids: chunk 级别标注（可选，后续补充）
    """
    id: str
    question: str
    expected_sources: List[str]
    category: str
    difficulty: str
    relevant_doc_ids: Optional[List[str]] = field(default=None)


def load_eval_dataset(
    json_path: str = "data/eval/qa_pairs.json",
) -> List[EvalSample]:
    """加载评估数据集，返回标准化的 EvalSample 列表。

    Args:
        json_path: QA pairs JSON 文件路径。

    Returns:
        EvalSample 列表。

    Raises:
        FileNotFoundError: JSON 文件不存在时抛出。
        KeyError: JSON 条目缺少必要字段时抛出。
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"评估数据集文件不存在: {json_path}")

    with open(path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    samples: List[EvalSample] = []
    for i, entry in enumerate(raw_data):
        try:
            sample = EvalSample(
                id=entry.get("id", f"q{i+1:03d}"),
                question=entry["question"],
                expected_sources=entry["expected_sources"],
                category=entry.get("category", "unknown"),
                difficulty=entry.get("difficulty", "medium"),
                relevant_doc_ids=entry.get("relevant_doc_ids"),
            )
            samples.append(sample)
        except KeyError as e:
            logger.warning("跳过数据，缺少字段", index=i, missing_field=str(e))

    return samples


def print_dataset_stats(samples: List[EvalSample]) -> None:
    """打印数据集统计信息。"""
    print(f"\n{'='*50}")
    print(f"评估数据集统计")
    print(f"{'='*50}")
    print(f"总样本数: {len(samples)}")

    # 难度分布
    difficulty_counts = Counter(s.difficulty for s in samples)
    print(f"\n难度分布:")
    for diff in ["easy", "medium", "hard"]:
        count = difficulty_counts.get(diff, 0)
        pct = count / len(samples) * 100 if samples else 0
        print(f"  {diff:8s}: {count:3d} ({pct:.0f}%)")

    # 分类分布
    category_counts = Counter(s.category for s in samples)
    print(f"\n分类分布 ({len(category_counts)} 个分类):")
    for cat, count in category_counts.most_common():
        print(f"  {cat:22s}: {count:3d}")

    # expected_sources 统计
    total_sources = sum(len(s.expected_sources) for s in samples)
    unique_sources = len(set(
        src for s in samples for src in s.expected_sources
    ))
    print(f"\n来源统计:")
    print(f"  总引用数: {total_sources}")
    print(f"  去重 URL: {unique_sources}")

    # 有 relevant_doc_ids 标注的比例
    annotated = sum(1 for s in samples if s.relevant_doc_ids)
    print(f"  chunk 级标注: {annotated}/{len(samples)}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    samples = load_eval_dataset()
    print_dataset_stats(samples)
