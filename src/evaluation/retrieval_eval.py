"""检索评估编排模块。

职责：
- 将检索结果与评估数据集匹配（Source URL 匹配策略）
- 聚合多 query 的指标（整体 + 按类别分组）
- 生成 Markdown 评估报告

设计原则：
- SourceMatcher 策略模式：当前精确匹配，可扩展模糊匹配
- QueryEvalResult / EvalReport 数据类：结构化存储，便于序列化和二次分析
- RetrievalEvaluator 编排类：协调 retriever + matcher + metrics
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import structlog

from src.evaluation.dataset import EvalSample
from src.evaluation.metrics import hit_rate_at_k, mrr_at_k, ndcg_at_k
from src.retriever.protocols import RetrieverProtocol

logger = structlog.get_logger(__name__)


# ============================================================
# Source 匹配策略（策略模式 — 开闭原则）
# ============================================================

class SourceMatcher(ABC):
    """文档来源匹配策略的抽象基类。

    为什么需要策略模式？
    - 当前使用精确 URL 匹配（同系统产出，格式一致）
    - 后续可能需要模糊匹配（URL 参数差异、路径归一化等）
    - 策略模式让匹配逻辑可独立替换，不影响评估器核心逻辑
    """

    @abstractmethod
    def match(self, retrieved_source: str, expected_sources: List[str]) -> bool:
        """判断检索到的文档来源是否匹配预期来源列表。"""


class ExactSourceMatcher(SourceMatcher):
    """精确 URL 匹配策略。

    逻辑：retrieved_source 是否在 expected_sources 列表中精确出现。
    适用场景：检索文档的 source URL 与评估数据集中的 expected_sources
    来自同一系统（爬取 → frontmatter → 入库 → 检索返回），格式一致。
    """

    def match(self, retrieved_source: str, expected_sources: List[str]) -> bool:
        return retrieved_source in expected_sources


# ============================================================
# 评估结果数据结构
# ============================================================

@dataclass
class QueryEvalResult:
    """单条 query 的评估结果。

    Attributes:
        query_id: 评估样本 ID，如 "q001"
        question: 原始中文问题
        category: 主题分类
        difficulty: 难度等级
        retrieved_sources: 检索返回的 source URL 列表（按排名顺序，去重）
        expected_sources: 预期命中的 source URL 列表
        metrics: 按 k 值分组的指标字典 {k: {"hit_rate": x, "mrr": x, "ndcg": x}}
    """
    query_id: str
    question: str
    category: str
    difficulty: str
    retrieved_sources: List[str]
    expected_sources: List[str]
    metrics: Dict[int, Dict[str, float]] = field(default_factory=dict)


@dataclass
class EvalReport:
    """整体评估报告。

    Attributes:
        evaluator_name: 评估器名称（如 "baseline"、"mmr_k5"）
        total_queries: 评估 query 总数
        ks: 评估的 k 值列表
        query_results: 每个 query 的详细评估结果
        overall_metrics: 整体平均指标 {k: {"hit_rate": x, "mrr": x, "ndcg": x}}
        category_metrics: 按类别分组的平均指标 {category: {k: {"hit_rate": x, ...}}}
    """
    evaluator_name: str
    total_queries: int
    ks: List[int]
    query_results: List[QueryEvalResult]
    overall_metrics: Dict[int, Dict[str, float]] = field(default_factory=dict)
    category_metrics: Dict[str, Dict[int, Dict[str, float]]] = field(default_factory=dict)


# ============================================================
# 检索评估器（编排类）
# ============================================================

class RetrievalEvaluator:
    """检索评估器：编排 检索 → 匹配 → 指标计算 → 聚合。"""

    def __init__(
        self,
        retriever: RetrieverProtocol,
        eval_samples: List[EvalSample],
        matcher: Optional[SourceMatcher] = None,
        ks: Optional[List[int]] = None,
        evaluator_name: str = "baseline",
    ):
        self.retriever = retriever
        self.eval_samples = eval_samples
        self.matcher = matcher or ExactSourceMatcher()
        self.ks = ks or [3]
        self.evaluator_name = evaluator_name

    def evaluate(self) -> EvalReport:
        """运行完整评估流程。

        流程：
        1. 遍历 eval_samples，逐条检索
        2. 提取检索结果的 source URL（用 matcher 匹配）
        3. 对每个 k 值计算 hit_rate, mrr, ndcg
        4. 聚合 overall_metrics 和 category_metrics
        5. 返回 EvalReport
        """
        query_results: List[QueryEvalResult] = []

        for i, sample in enumerate(self.eval_samples, 1):
            logger.info(
                "评估中",
                progress=f"{i}/{len(self.eval_samples)}",
                query_id=sample.id,
                question=sample.question[:40],
            )

            # 检索并提取 source URL
            retrieved_sources = self._retrieve_and_extract(sample.question)

            # 对每个 k 值计算三个指标
            metrics_by_k: Dict[int, Dict[str, float]] = {}
            for k in self.ks:
                metrics_by_k[k] = {
                    "hit_rate": hit_rate_at_k(retrieved_sources, sample.expected_sources, k),
                    "mrr": mrr_at_k(retrieved_sources, sample.expected_sources, k),
                    "ndcg": ndcg_at_k(retrieved_sources, sample.expected_sources, k),
                }

            # 记录结果
            query_results.append(QueryEvalResult(
                query_id=sample.id,
                question=sample.question,
                category=sample.category,
                difficulty=sample.difficulty,
                retrieved_sources=retrieved_sources,
                expected_sources=sample.expected_sources,
                metrics=metrics_by_k,
            ))

        # 聚合指标
        overall_metrics, category_metrics = self._aggregate_metrics(query_results)

        return EvalReport(
            evaluator_name=self.evaluator_name,
            total_queries=len(query_results),
            ks=self.ks,
            query_results=query_results,
            overall_metrics=overall_metrics,
            category_metrics=category_metrics,
        )

    def _retrieve_and_extract(self, query: str) -> List[str]:
        """执行检索并提取去重的 source URL 列表（保持排名顺序）。

        关键逻辑：
        - 同一 source 可能有多个 chunk 被检索到
        - 需要去重但保持首次出现的排名顺序
        - 用 dict.fromkeys 实现去重 + 保序
        """
        docs = self.retriever.invoke(query)

        # 提取 source URL，缺失则用空字符串占位
        sources = [doc.metadata.get("source", "") for doc in docs]

        # 去重保序：同一 source 的多个 chunk 只保留首次出现
        seen = dict.fromkeys(sources)
        # 过滤掉空字符串（元数据缺失的文档）
        return [s for s in seen if s]

    @staticmethod
    def _aggregate_metrics(
        query_results: List[QueryEvalResult],
    ) -> tuple:
        """聚合整体指标和按类别分组指标。

        Returns:
            (overall_metrics, category_metrics)
        """
        if not query_results:
            return {}, {}

        # 整体指标：对所有 query 取平均
        ks = query_results[0].metrics.keys()
        overall: Dict[int, Dict[str, float]] = {}
        for k in ks:
            overall[k] = {
                metric: sum(r.metrics[k][metric] for r in query_results) / len(query_results)
                for metric in ("hit_rate", "mrr", "ndcg")
            }

        # 分类指标：按 category 分组后取平均
        categories = set(r.category for r in query_results)
        by_category: Dict[str, Dict[int, Dict[str, float]]] = {}
        for cat in sorted(categories):
            cat_results = [r for r in query_results if r.category == cat]
            by_category[cat] = {}
            for k in ks:
                by_category[cat][k] = {
                    metric: sum(r.metrics[k][metric] for r in cat_results) / len(cat_results)
                    for metric in ("hit_rate", "mrr", "ndcg")
                }

        return overall, by_category

    @staticmethod
    def generate_report(report: EvalReport) -> str:
        """将 EvalReport 转为 Markdown 格式字符串。

        报告结构：
        1. 标题 + 概览
        2. 整体指标表格
        3. 按类别分组指标表格
        4. 每个 query 的详细得分表格
        """
        lines: List[str] = []

        # --- 1. 标题 + 概览 ---
        lines.append(f"# 检索评估报告: {report.evaluator_name}")
        lines.append("")
        lines.append(f"- **评估 Query 总数**: {report.total_queries}")
        lines.append(f"- **评估 k 值**: {report.ks}")
        lines.append("")

        # --- 2. 整体指标表格 ---
        lines.append("## 整体指标")
        lines.append("")
        lines.append("| k | Hit Rate | MRR | NDCG |")
        lines.append("|---|----------|-----|------|")
        for k in report.ks:
            m = report.overall_metrics.get(k, {})
            lines.append(
                f"| {k} | {m.get('hit_rate', 0):.4f} | "
                f"{m.get('mrr', 0):.4f} | {m.get('ndcg', 0):.4f} |"
            )
        lines.append("")

        # --- 3. 按类别分组指标表格 ---
        if report.category_metrics:
            lines.append("## 按类别分组指标")
            lines.append("")
            for k in report.ks:
                lines.append(f"### k={k}")
                lines.append("")
                lines.append("| 类别 | 样本数 | Hit Rate | MRR | NDCG |")
                lines.append("|------|--------|----------|-----|------|")
                for cat, cat_metrics in sorted(report.category_metrics.items()):
                    m = cat_metrics.get(k, {})
                    # 统计该类别的样本数
                    cat_count = sum(
                        1 for r in report.query_results if r.category == cat
                    )
                    lines.append(
                        f"| {cat} | {cat_count} | "
                        f"{m.get('hit_rate', 0):.4f} | "
                        f"{m.get('mrr', 0):.4f} | "
                        f"{m.get('ndcg', 0):.4f} |"
                    )
                lines.append("")

        # --- 4. 逐 query 详细得分表格 ---
        lines.append("## 逐 Query 详细得分")
        lines.append("")
        for k in report.ks:
            lines.append(f"### k={k}")
            lines.append("")
            lines.append("| ID | 问题 | 类别 | 难度 | Hit Rate | MRR | NDCG |")
            lines.append("|----|------|------|------|----------|-----|------|")
            for r in report.query_results:
                m = r.metrics.get(k, {})
                # 截断问题以保持表格整洁
                q_short = r.question[:25] + "..." if len(r.question) > 25 else r.question
                lines.append(
                    f"| {r.query_id} | {q_short} | {r.category} | "
                    f"{r.difficulty} | {m.get('hit_rate', 0):.4f} | "
                    f"{m.get('mrr', 0):.4f} | {m.get('ndcg', 0):.4f} |"
                )
            lines.append("")

        return "\n".join(lines)


# ============================================================
# CLI 入口（运行 Baseline 评估）
# ============================================================

def run_baseline_eval(
    qa_path: Optional[str] = None,
    output_path: Optional[str] = None,
    ks: Optional[List[int]] = None,
    search_type: str = "similarity",
    search_k: int = 10,
) -> EvalReport:
    """运行 Baseline 检索评估并保存报告。

    Args:
        qa_path: QA pairs JSON 文件路径。默认从 settings.eval_qa_path 读取。
        output_path: 评估报告输出路径。默认从 settings.eval_report_path 读取。
        ks: 评估的 k 值列表，默认 [3, 5, 10]。
        search_type: 检索器搜索类型。
        search_k: 检索器返回的文档数量（需 >= max(ks)）。

    Returns:
        EvalReport 实例。
    """
    from src.core.config import settings
    from src.core.factories import create_retriever
    from src.evaluation.dataset import load_eval_dataset

    # 从 settings 读取默认路径
    if qa_path is None:
        qa_path = settings.eval_qa_path
    if output_path is None:
        output_path = settings.eval_report_path

    # 步骤 1：加载评估数据集
    logger.info("加载评估数据集", path=qa_path)
    samples = load_eval_dataset(qa_path)

    # 步骤 2：创建检索器（通过工厂函数，配置驱动）
    if ks is None:
        ks = [3, 5, 10]
    retriever = create_retriever(
        settings,
        search_type=search_type,
        search_kwargs={"k": search_k},
    )

    # 步骤 3：创建评估器并运行评估
    evaluator = RetrievalEvaluator(
        retriever=retriever,
        eval_samples=samples,
        ks=ks,
        evaluator_name=f"baseline_{search_type}_top{search_k}",
    )
    report = evaluator.evaluate()

    # 步骤 4：生成报告并保存
    md_content = RetrievalEvaluator.generate_report(report)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md_content, encoding="utf-8")
    logger.info("评估报告已保存", path=str(output))

    # 步骤 5：打印概览
    print(f"\n{'='*60}")
    print(f"检索评估完成: {report.evaluator_name}")
    print(f"{'='*60}")
    for k in report.ks:
        m = report.overall_metrics.get(k, {})
        print(f"  k={k}: Hit Rate={m.get('hit_rate', 0):.4f}, "
              f"MRR={m.get('mrr', 0):.4f}, "
              f"NDCG={m.get('ndcg', 0):.4f}")
    print(f"{'='*60}\n")

    return report


if __name__ == "__main__":
    run_baseline_eval()
