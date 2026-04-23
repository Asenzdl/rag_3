"""CitationExtractor 单元测试。

覆盖场景：
1. 正则提取策略：正常路径、边界情况、异常路径
2. 结构化输出策略：正常路径、模型不支持回退
3. URL 验证逻辑
4. 数据结构正确性

python.exe -m pytest tests/test_citation_chain.py tests/test_rag_chain.py -v --tb=short 2>&1
python.exe -c "from src.generation.citation_chain import CitationExtractor; print('citation_chain OK')"
"""

import pytest
from unittest.mock import MagicMock, patch

from src.generation.citation_chain import (
    CITATION_EXTRACTION_PROMPT,
    Citation,
    CitationExtractor,
    CitationItem,
    CitationList,
    ValidatedCitation,
)
from src.generation.exceptions import CitationExtractionError


# ============================================================
# 测试数据
# ============================================================

# 模拟一个典型的 RAG 回答文本（中文回答 + 来源列表）
SAMPLE_ANSWER = (
    "LangGraph 是一个用于构建有状态、多参与者 LLM 应用的框架，"
    "它通过基于图的工作流编排扩展了 LangChain[1]。"
    "其核心类是 StateGraph，通过定义节点和边来构建 Agent 工作流[2]。\n\n"
    "来源：\n"
    "[1] https://langchain-ai.github.io/langgraph/concepts/low_level/\n"
    "[2] https://langchain-ai.github.io/langgraph/how-tos/map_reduce/"
)

SAMPLE_SOURCES = [
    "https://langchain-ai.github.io/langgraph/concepts/low_level/",
    "https://langchain-ai.github.io/langgraph/how-tos/map_reduce/",
]

# 包含幻觉引用的回答（URL 不在 sources 中）
ANSWER_WITH_HALLUCINATION = (
    "LangGraph 支持多种功能[1]。\n\n"
    "来源：\n"
    "[1] https://fake-url.example.com/not-exist"
)


# ============================================================
# ValidatedCitation 数据结构测试
# ============================================================

class TestValidatedCitation:
    """ValidatedCitation 数据结构测试。"""

    def test_creation(self):
        """测试 ValidatedCitation 创建和属性访问。"""
        citation = ValidatedCitation(number=1, url="https://example.com", is_valid=True)
        assert citation.number == 1
        assert citation.url == "https://example.com"
        assert citation.is_valid is True

    def test_inherits_citation(self):
        """测试 ValidatedCitation 继承自 Citation。"""
        citation = ValidatedCitation(number=2, url="https://test.com", is_valid=False)
        assert isinstance(citation, Citation)

    def test_invalid_citation(self):
        """测试 is_valid=False 的引用。"""
        citation = ValidatedCitation(number=3, url="https://fake.com", is_valid=False)
        assert citation.is_valid is False


# ============================================================
# Pydantic Schema 测试
# ============================================================

class TestPydanticSchema:
    """结构化输出的 Pydantic Schema 测试。"""

    def test_citation_item_creation(self):
        """测试 CitationItem 创建。"""
        item = CitationItem(number=1, url="https://example.com")
        assert item.number == 1
        assert item.url == "https://example.com"

    def test_citation_list_creation(self):
        """测试 CitationList 创建。"""
        items = [
            CitationItem(number=1, url="https://example.com/1"),
            CitationItem(number=2, url="https://example.com/2"),
        ]
        citation_list = CitationList(citations=items)
        assert len(citation_list.citations) == 2
        assert citation_list.citations[0].number == 1

    def test_citation_list_empty(self):
        """测试 CitationList 空列表。"""
        citation_list = CitationList(citations=[])
        assert len(citation_list.citations) == 0


# ============================================================
# 正则提取策略测试
# ============================================================

class TestRegexExtraction:
    """正则提取策略测试。"""

    def setup_method(self):
        """每个测试方法前创建默认的 CitationExtractor（正则策略）。"""
        self.extractor = CitationExtractor()

    def test_normal_extraction(self):
        """正常路径：从标准格式回答中提取引用。"""
        citations = self.extractor.extract(SAMPLE_ANSWER, SAMPLE_SOURCES)

        assert len(citations) == 2
        # 第一个引用
        assert citations[0].number == 1
        assert citations[0].url == "https://langchain-ai.github.io/langgraph/concepts/low_level/"
        assert citations[0].is_valid is True
        # 第二个引用
        assert citations[1].number == 2
        assert citations[1].url == "https://langchain-ai.github.io/langgraph/how-tos/map_reduce/"
        assert citations[1].is_valid is True

    def test_hallucination_detection(self):
        """异常路径：检测到幻觉引用（URL 不在 sources 中）。"""
        citations = self.extractor.extract(
            ANSWER_WITH_HALLUCINATION,
            SAMPLE_SOURCES,
        )

        assert len(citations) == 1
        assert citations[0].number == 1
        assert citations[0].url == "https://fake-url.example.com/not-exist"
        assert citations[0].is_valid is False

    def test_empty_answer(self):
        """边界情况：空回答文本。"""
        citations = self.extractor.extract("", SAMPLE_SOURCES)
        assert citations == []

    def test_whitespace_answer(self):
        """边界情况：只有空白的回答文本。"""
        citations = self.extractor.extract("   \n  \t  ", SAMPLE_SOURCES)
        assert citations == []

    def test_no_citations_in_answer(self):
        """边界情况：回答中没有引用格式。"""
        answer = "这是一个没有引用的回答。"
        citations = self.extractor.extract(answer, SAMPLE_SOURCES)
        assert citations == []

    def test_empty_sources(self):
        """边界情况：sources 列表为空。"""
        citations = self.extractor.extract(SAMPLE_ANSWER, [])
        assert len(citations) == 2
        # 所有引用的 is_valid 都应为 False
        assert all(not c.is_valid for c in citations)

    def test_deduplication(self):
        """边界情况：去重 — 同一 (number, url) 只保留一个。

        LLM 可能在回答正文和来源列表中各出现一次 [1] URL，
        正则会匹配到两次，应去重。
        """
        # 构造重复引用的回答
        answer_with_dup = (
            "正文引用[1] https://example.com/doc1\n\n"
            "来源：\n"
            "[1] https://example.com/doc1"
        )
        sources = ["https://example.com/doc1"]
        citations = self.extractor.extract(answer_with_dup, sources)

        # 去重后应只有一个
        assert len(citations) == 1
        assert citations[0].number == 1

    def test_url_trailing_punctuation_cleanup(self):
        """边界情况：URL 尾部标点清理。

        #   正则 \\S+ 可能捕获 URL 末尾紧跟的 ) 或 .
        """
        # URL 末尾有右括号（常见于 Markdown 列表格式）
        answer = "参考[1] https://example.com/doc1)\n[2] https://example.com/doc2."
        sources = ["https://example.com/doc1", "https://example.com/doc2"]
        citations = self.extractor.extract(answer, sources)

        assert len(citations) == 2
        # 右括号和句号应被清理掉
        assert citations[0].url == "https://example.com/doc1"
        assert citations[1].url == "https://example.com/doc2"

    def test_sorted_by_number(self):
        """结果按 number 排序。"""
        # 故意乱序的回答
        answer = (
            "[3] https://example.com/3\n"
            "[1] https://example.com/1\n"
            "[2] https://example.com/2"
        )
        sources = ["https://example.com/1", "https://example.com/2", "https://example.com/3"]
        citations = self.extractor.extract(answer, sources)

        numbers = [c.number for c in citations]
        assert numbers == sorted(numbers)

    def test_mixed_valid_invalid_citations(self):
        """混合场景：部分引用有效，部分无效。"""
        answer = (
            "引用了真实文档[1]和虚假文档[2]。\n\n"
            "来源：\n"
            "[1] https://example.com/real\n"
            "[2] https://example.com/fake"
        )
        sources = ["https://example.com/real"]
        citations = self.extractor.extract(answer, sources)

        assert len(citations) == 2
        assert citations[0].is_valid is True
        assert citations[1].is_valid is False

    def test_http_url(self):
        """边界情况：http（非 https）URL 也应被匹配。"""
        answer = "参考[1] http://example.com/doc1"
        sources = ["http://example.com/doc1"]
        citations = self.extractor.extract(answer, sources)

        assert len(citations) == 1
        assert citations[0].url == "http://example.com/doc1"
        assert citations[0].is_valid is True


# ============================================================
# 结构化输出策略测试
# ============================================================

class TestStructuredExtraction:
    """结构化输出策略测试。"""

    def test_structured_output_success(self):
        """正常路径：结构化输出成功提取引用。"""
        # 创建 mock LLM，模拟 with_structured_output 行为
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        # 使用与 SAMPLE_SOURCES 一致的 URL
        mock_structured.invoke.return_value = CitationList(citations=[
            CitationItem(number=1, url="https://langchain-ai.github.io/langgraph/concepts/low_level/"),
            CitationItem(number=2, url="https://langchain-ai.github.io/langgraph/how-tos/map_reduce/"),
        ])
        mock_llm.with_structured_output.return_value = mock_structured

        extractor = CitationExtractor(llm=mock_llm, use_structured_output=True)
        citations = extractor.extract(SAMPLE_ANSWER, SAMPLE_SOURCES)

        assert len(citations) == 2
        assert citations[0].is_valid is True
        assert citations[1].is_valid is True

    def test_structured_output_fallback_on_not_implemented(self):
        """异常路径：模型不支持 Function Calling 时回退到正则。"""
        mock_llm = MagicMock()
        # with_structured_output 抛出 NotImplementedError
        mock_llm.with_structured_output.side_effect = NotImplementedError(
            "Model does not support function calling"
        )

        extractor = CitationExtractor(llm=mock_llm, use_structured_output=True)
        # 应回退到正则策略，不抛异常
        citations = extractor.extract(SAMPLE_ANSWER, SAMPLE_SOURCES)

        assert len(citations) == 2  # 正则策略的预期结果

    def test_structured_output_fallback_on_general_error(self):
        """异常路径：结构化输出一般异常时包装为 CitationExtractionError 并向上传播。"""
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.side_effect = RuntimeError("Unexpected error")
        mock_llm.with_structured_output.return_value = mock_structured

        extractor = CitationExtractor(llm=mock_llm, use_structured_output=True)
        # RuntimeError 被 _extract_structured 包装为 CitationExtractionError，
        # extract() 内部 except CitationExtractionError: raise 向上传播
        with pytest.raises(CitationExtractionError):
            extractor.extract(SAMPLE_ANSWER, SAMPLE_SOURCES)

    def test_citation_extraction_error_propagates(self):
        """CitationExtractionError 从 _extract_structured 传播到 extract() 外层。"""
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        # 模拟 _extract_structured 内部抛出 CitationExtractionError
        mock_structured.invoke.side_effect = CitationExtractionError("解析失败")
        mock_llm.with_structured_output.return_value = mock_structured

        extractor = CitationExtractor(llm=mock_llm, use_structured_output=True)
        with pytest.raises(CitationExtractionError, match="解析失败"):
            extractor.extract(SAMPLE_ANSWER, SAMPLE_SOURCES)

    def test_structured_output_without_llm(self):
        """边界情况：启用结构化输出但未提供 LLM，回退到正则。"""
        extractor = CitationExtractor(use_structured_output=True)
        # 构造函数中应自动回退为 use_structured_output=False
        assert extractor._use_structured_output is False

        # 应使用正则策略
        citations = extractor.extract(SAMPLE_ANSWER, SAMPLE_SOURCES)
        assert len(citations) == 2


# ============================================================
# _validate_url 测试
# ============================================================

class TestValidateUrl:
    """URL 验证测试。"""

    def setup_method(self):
        self.extractor = CitationExtractor()

    def test_valid_url(self):
        """URL 在 sources 集合中。"""
        sources_set = {"https://example.com/doc1", "https://example.com/doc2"}
        assert self.extractor._validate_url("https://example.com/doc1", sources_set) is True

    def test_invalid_url(self):
        """URL 不在 sources 集合中。"""
        sources_set = {"https://example.com/doc1"}
        assert self.extractor._validate_url("https://example.com/fake", sources_set) is False

    def test_empty_sources_set(self):
        """sources 集合为空。"""
        assert self.extractor._validate_url("https://example.com/doc1", set()) is False

    def test_exact_match_required(self):
        """精确匹配 — URL 必须完全一致。"""
        sources_set = {"https://example.com/doc1"}
        # 少一个尾部斜杠
        assert self.extractor._validate_url("https://example.com/doc1/", sources_set) is False
        # http vs https
        assert self.extractor._validate_url("http://example.com/doc1", sources_set) is False


# ============================================================
# 正则模式测试
# ============================================================

class TestCitationPattern:
    """CITATION_PATTERN 正则模式测试。"""

    def test_pattern_matches_standard_format(self):
        """标准格式 [N] URL 能被匹配。"""
        import re
        # 从 CitationExtractor 类获取 CITATION_PATTERN
        pattern = CitationExtractor.CITATION_PATTERN
        text = "[1] https://example.com/doc1"
        matches = re.findall(pattern, text)
        assert len(matches) == 1
        assert matches[0] == ("1", "https://example.com/doc1")

    def test_pattern_no_match_inline_reference(self):
        """正文中的行内引用 [N] 后跟中文文字不应匹配。"""
        import re
        pattern = CitationExtractor.CITATION_PATTERN
        text = "LangGraph 是一个框架[1]，它扩展了 LangChain"
        matches = re.findall(pattern, text)
        assert len(matches) == 0

    def test_pattern_matches_multiple(self):
        """多个引用格式能被全部匹配。"""
        import re
        pattern = CitationExtractor.CITATION_PATTERN
        text = (
            "[1] https://example.com/1\n"
            "[2] https://example.com/2\n"
            "[3] https://example.com/3"
        )
        matches = re.findall(pattern, text)
        assert len(matches) == 3
