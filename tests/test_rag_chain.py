"""RAGChain 单元测试。

覆盖场景：
1. invoke 方法：正常路径、空检索拦截、异常处理
2. stream 方法：正常路径、空检索、生成失败
3. retrieve 方法：正常路径、检索异常
4. extract_citations 方法：正常路径、提取失败
5. format_docs 函数
6. RAGResponse 数据结构
"""

import pytest
from dataclasses import asdict
from unittest.mock import MagicMock, patch, PropertyMock

from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from src.generation.rag_chain import (
    RAGChain,
    RAGResponse,
    format_docs,
)
from src.generation.citation_chain import ValidatedCitation
from src.generation.exceptions import (
    CitationExtractionError,
    EmptyRetrievalError,
    GenerationError,
    LLMCallError,
)
from src.generation.prompts import PromptVersion, get_prompt


# ============================================================
# 测试辅助函数
# ============================================================

def create_mock_docs(count: int = 3) -> list:
    """创建模拟的检索文档列表。

    Args:
        count: 文档数量

    Returns:
        List[Document]，每个文档包含 page_content 和 metadata["source"]
    """
    docs = []
    for i in range(1, count + 1):
        docs.append(Document(
            page_content=f"这是第 {i} 个文档的内容，关于 LangGraph 的功能描述。",
            metadata={"source": f"https://example.com/doc{i}"},
        ))
    return docs


def create_mock_retriever(docs=None):
    """创建 mock 检索器。

    Args:
        docs: 检索器返回的文档列表，默认为 3 个模拟文档
    """
    if docs is None:
        docs = create_mock_docs(3)
    retriever = MagicMock()
    retriever.invoke.return_value = docs
    return retriever


def create_mock_llm(answer="这是模拟的回答[1][2]。"):
    """创建 mock LLM。

    Args:
        answer: LLM 返回的回答文本
    """
    llm = MagicMock()
    # 模拟 | 操作符链式调用：prompt | llm | StrOutputParser
    # llm.invoke 应返回 AIMessage
    llm.invoke.return_value = AIMessage(content=answer)
    llm.stream.return_value = iter([answer[:10], answer[10:]])
    return llm


def create_mock_chain_components(answer="这是模拟的回答[1][2]。"):
    """创建 mock 的链组件（retriever + llm + prompt）。"""
    docs = create_mock_docs(3)
    retriever = create_mock_retriever(docs)
    llm = create_mock_llm(answer)
    prompt = get_prompt(PromptVersion.V1)
    return retriever, llm, prompt, docs


# ============================================================
# format_docs 测试
# ============================================================

class TestFormatDocs:
    """format_docs 函数测试。"""

    def test_normal_format(self):
        """正常路径：格式化 3 个文档。"""
        docs = create_mock_docs(3)
        result = format_docs(docs)

        # 应包含编号 [1] [2] [3]
        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" in result
        # 应包含 source URL
        assert "https://example.com/doc1" in result
        assert "https://example.com/doc2" in result
        assert "https://example.com/doc3" in result
        # 应包含 (source: URL) 格式
        assert "(source: https://example.com/doc1)" in result

    def test_empty_docs(self):
        """边界情况：空文档列表返回空字符串。"""
        assert format_docs([]) == ""

    def test_single_doc(self):
        """边界情况：单个文档。"""
        docs = [Document(
            page_content="内容",
            metadata={"source": "https://example.com/1"},
        )]
        result = format_docs(docs)
        assert "[1] 内容 (source: https://example.com/1)" == result

    def test_doc_without_source(self):
        """边界情况：文档缺少 source 元数据，使用 unknown 占位。"""
        docs = [Document(page_content="内容", metadata={})]
        result = format_docs(docs)
        assert "(source: unknown)" in result

    def test_doc_with_empty_content_skipped(self):
        """边界情况：page_content 为空的文档被跳过。"""
        docs = [
            Document(page_content="有内容", metadata={"source": "https://example.com/1"}),
            Document(page_content="", metadata={"source": "https://example.com/2"}),
            Document(page_content="   ", metadata={"source": "https://example.com/3"}),
        ]
        result = format_docs(docs)
        # 只有第一个文档被格式化
        assert "[1]" in result
        assert "[2]" not in result

    def test_docs_separated_by_double_newline(self):
        """文档间以双换行分隔。"""
        docs = create_mock_docs(2)
        result = format_docs(docs)
        assert "\n\n" in result

    def test_format_matches_fewshot_style(self):
        """格式化输出与 Prompt few-shot 示例格式一致。"""
        docs = [
            Document(
                page_content="LangGraph is a framework for building stateful applications.",
                metadata={"source": "https://langchain-ai.github.io/langgraph/overview/"},
            )
        ]
        result = format_docs(docs)
        # 格式应为：[1] content (source: URL)
        expected_pattern = "[1] LangGraph is a framework for building stateful applications. (source: https://langchain-ai.github.io/langgraph/overview/)"
        assert result == expected_pattern


# ============================================================
# RAGResponse 测试
# ============================================================

class TestRAGResponse:
    """RAGResponse 数据结构测试。"""

    def test_creation(self):
        """测试 RAGResponse 创建和属性访问。"""
        citations = [ValidatedCitation(number=1, url="https://example.com", is_valid=True)]
        response = RAGResponse(
            answer="回答文本",
            sources=["https://example.com"],
            citations=citations,
            retrieval_count=1,
        )
        assert response.answer == "回答文本"
        assert len(response.sources) == 1
        assert len(response.citations) == 1
        assert response.retrieval_count == 1

    def test_to_dict(self):
        """测试 to_dict 方法。"""
        citations = [
            ValidatedCitation(number=1, url="https://example.com/1", is_valid=True),
            ValidatedCitation(number=2, url="https://fake.com", is_valid=False),
        ]
        response = RAGResponse(
            answer="回答",
            sources=["https://example.com/1"],
            citations=citations,
            retrieval_count=2,
        )
        result = response.to_dict()

        assert result["answer"] == "回答"
        assert result["sources"] == ["https://example.com/1"]
        assert len(result["citations"]) == 2
        assert result["citations"][0] == {"number": 1, "url": "https://example.com/1", "is_valid": True}
        assert result["citations"][1] == {"number": 2, "url": "https://fake.com", "is_valid": False}
        assert result["retrieval_count"] == 2


# ============================================================
# RAGChain.invoke 测试
# ============================================================

class TestRAGChainInvoke:
    """RAGChain.invoke 方法测试。"""

    def setup_method(self):
        """每个测试方法前创建 mock 组件。"""
        self.answer_text = (
            "LangGraph 是一个框架[1]。它扩展了 LangChain[2]。\n\n"
            "来源：\n"
            "[1] https://example.com/doc1\n"
            "[2] https://example.com/doc2"
        )
        self.retriever, self.llm, self.prompt, self.docs = create_mock_chain_components(
            self.answer_text
        )

    def _create_chain(self, **kwargs):
        """创建 RAGChain 实例（使用 mock 组件）。

        Task 1.7 改动：invoke 方法使用 _retryable_invoke（返回 AIMessage），
        因此需要 mock _retryable_invoke 而非 _generation_chain。
        """
        chain = RAGChain(
            retriever=self.retriever,
            llm=self.llm,
            prompt=self.prompt,
            **kwargs,
        )
        # 替换 _retryable_invoke 为 mock，返回 AIMessage
        mock_ai_message = AIMessage(content=self.answer_text)
        mock_ai_message.usage_metadata = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
        chain._retryable_invoke = MagicMock(return_value=mock_ai_message)
        return chain

    def test_normal_invoke(self):
        """正常路径：完整的 RAG 管道。"""
        chain = self._create_chain()
        result = chain.invoke("LangGraph 是什么？")

        assert isinstance(result, RAGResponse)
        assert result.retrieval_count == 3
        assert len(result.sources) == 3
        assert result.answer == self.answer_text

    def test_empty_retrieval_returns_preset_response(self):
        """空检索拦截：返回预设回复，不调用 LLM。"""
        empty_retriever = create_mock_retriever(docs=[])
        chain = RAGChain(
            retriever=empty_retriever,
            llm=self.llm,
            prompt=self.prompt,
        )
        result = chain.invoke("无关问题")

        assert result.answer == RAGChain.EMPTY_RETRIEVAL_RESPONSE
        assert result.sources == []
        assert result.citations == []
        assert result.retrieval_count == 0

    def test_empty_retrieval_with_raise_on_empty(self):
        """空检索 + raise_on_empty=True：抛出 EmptyRetrievalError。"""
        empty_retriever = create_mock_retriever(docs=[])
        chain = RAGChain(
            retriever=empty_retriever,
            llm=self.llm,
            prompt=self.prompt,
            raise_on_empty=True,
        )

        with pytest.raises(EmptyRetrievalError):
            chain.invoke("无关问题")

    def test_custom_empty_retrieval_response(self):
        """自定义空检索回复。"""
        custom_response = "自定义的空检索回复"
        empty_retriever = create_mock_retriever(docs=[])
        chain = RAGChain(
            retriever=empty_retriever,
            llm=self.llm,
            prompt=self.prompt,
            empty_retrieval_response=custom_response,
        )
        result = chain.invoke("无关问题")

        assert result.answer == custom_response

    def test_llm_call_error_wrapping(self):
        """LLM 调用失败：包装为 LLMCallError。"""
        chain = self._create_chain()
        # 模拟 LLM 调用失败（_retryable_invoke 重试耗尽后抛出异常）
        chain._retryable_invoke = MagicMock(side_effect=RuntimeError("API Error"))

        with pytest.raises(LLMCallError) as exc_info:
            chain.invoke("测试问题")

        assert exc_info.value.original_error is not None
        assert exc_info.value.is_retryable is False

    def test_retrieval_error_wrapping(self):
        """检索失败：包装为 GenerationError。"""
        from src.retriever.base_retriever import RetrievalError
        error_retriever = MagicMock()
        error_retriever.invoke.side_effect = RetrievalError("连接失败")

        chain = RAGChain(
            retriever=error_retriever,
            llm=self.llm,
            prompt=self.prompt,
        )

        with pytest.raises(GenerationError):
            chain.invoke("测试问题")

    def test_citation_extraction_failure_not_fatal(self):
        """引用提取失败不中断主流程。"""
        chain = self._create_chain()

        # mock citation_extractor.extract 抛出异常
        chain._citation_extractor.extract = MagicMock(
            side_effect=CitationExtractionError("提取失败")
        )

        result = chain.invoke("测试问题")
        # 回答仍然返回
        assert result.answer == self.answer_text
        # 但引用为空
        assert result.citations == []

    def test_citation_extraction_success(self):
        """引用提取成功：结果包含 ValidatedCitation。"""
        chain = self._create_chain()
        result = chain.invoke("LangGraph 是什么？")

        # 应有引用（正则从 answer_text 中提取）
        assert len(result.citations) > 0
        assert isinstance(result.citations[0], ValidatedCitation)


# ============================================================
# RAGChain.stream 测试
# ============================================================

class TestRAGChainStream:
    """RAGChain.stream 方法测试。"""

    def setup_method(self):
        """每个测试方法前创建 mock 组件。"""
        self.retriever, self.llm, self.prompt, self.docs = create_mock_chain_components()

    def _create_chain(self):
        chain = RAGChain(
            retriever=self.retriever,
            llm=self.llm,
            prompt=self.prompt,
        )
        # 替换 _generation_chain 为 mock，模拟流式输出
        mock_gen_chain = MagicMock()
        mock_gen_chain.stream.return_value = iter(["chunk1", "chunk2", "chunk3"])
        chain._generation_chain = mock_gen_chain
        return chain

    def test_stream_returns_chunks(self):
        """正常路径：流式输出返回多个 chunk。"""
        chain = self._create_chain()
        chunks = list(chain.stream("测试问题"))

        assert chunks == ["chunk1", "chunk2", "chunk3"]

    def test_stream_empty_retrieval(self):
        """空检索：流式返回预设回复。"""
        empty_retriever = create_mock_retriever(docs=[])
        chain = RAGChain(
            retriever=empty_retriever,
            llm=self.llm,
            prompt=self.prompt,
        )
        chunks = list(chain.stream("无关问题"))

        # 应只 yield 一个预设回复
        assert len(chunks) == 1
        assert chunks[0] == RAGChain.EMPTY_RETRIEVAL_RESPONSE

    def test_stream_generation_error(self):
        """生成失败：流式输出错误提示文本。"""
        chain = self._create_chain()
        chain._generation_chain.stream.side_effect = RuntimeError("LLM 崩溃")

        chunks = list(chain.stream("测试问题"))
        # 应包含错误提示
        assert any("生成失败" in chunk for chunk in chunks)

    def test_stream_retrieval_error(self):
        """检索失败：流式输出错误提示。"""
        from src.retriever.base_retriever import RetrievalError
        error_retriever = MagicMock()
        error_retriever.invoke.side_effect = RetrievalError("连接失败")

        chain = RAGChain(
            retriever=error_retriever,
            llm=self.llm,
            prompt=self.prompt,
        )
        chunks = list(chain.stream("测试问题"))
        assert any("检索失败" in chunk for chunk in chunks)


# ============================================================
# RAGChain.retrieve 测试
# ============================================================

class TestRAGChainRetrieve:
    """RAGChain.retrieve 方法测试。"""

    def test_retrieve_returns_docs(self):
        """正常路径：返回文档列表。"""
        docs = create_mock_docs(2)
        retriever = create_mock_retriever(docs)
        chain = RAGChain(
            retriever=retriever,
            llm=create_mock_llm(),
            prompt=get_prompt(PromptVersion.V1),
        )

        result = chain.retrieve("测试问题")
        assert len(result) == 2
        assert isinstance(result[0], Document)

    def test_retrieve_error_wrapping(self):
        """检索失败：包装为 GenerationError。"""
        from src.retriever.base_retriever import RetrievalError
        error_retriever = MagicMock()
        error_retriever.invoke.side_effect = RetrievalError("连接失败")

        chain = RAGChain(
            retriever=error_retriever,
            llm=create_mock_llm(),
            prompt=get_prompt(PromptVersion.V1),
        )

        with pytest.raises(GenerationError):
            chain.retrieve("测试问题")


# ============================================================
# RAGChain.extract_citations 测试
# ============================================================

class TestRAGChainExtractCitations:
    """RAGChain.extract_citations 方法测试。"""

    def test_extract_citations_success(self):
        """正常路径：提取引用。"""
        chain = RAGChain(
            retriever=create_mock_retriever(),
            llm=create_mock_llm(),
            prompt=get_prompt(PromptVersion.V1),
        )

        answer = "参考[1] https://example.com/doc1"
        sources = ["https://example.com/doc1"]
        citations = chain.extract_citations(answer, sources)

        assert len(citations) >= 1
        assert citations[0].is_valid is True

    def test_extract_citations_failure_returns_empty(self):
        """引用提取失败返回空列表。"""
        chain = RAGChain(
            retriever=create_mock_retriever(),
            llm=create_mock_llm(),
            prompt=get_prompt(PromptVersion.V1),
        )
        # mock citation_extractor 抛出异常
        chain._citation_extractor.extract = MagicMock(
            side_effect=CitationExtractionError("失败")
        )

        citations = chain.extract_citations("answer", ["source"])
        assert citations == []


# ============================================================
# RAGChain.ainvoke 测试
# ============================================================

class TestRAGChainAinvoke:
    """RAGChain.ainvoke 方法测试。"""

    def test_ainvoke_calls_invoke(self):
        """当前实现：ainvoke 委托给 invoke。"""
        chain = RAGChain(
            retriever=create_mock_retriever(),
            llm=create_mock_llm(),
            prompt=get_prompt(PromptVersion.V1),
        )
        # mock invoke 方法
        expected = RAGResponse(
            answer="测试回答", sources=[], citations=[], retrieval_count=0
        )
        chain.invoke = MagicMock(return_value=expected)

        # ainvoke 是 async，但当前实现直接调用 invoke
        # 使用 asyncio.run 测试
        import asyncio
        result = asyncio.run(chain.ainvoke("测试问题"))
        assert result == expected
        chain.invoke.assert_called_once_with("测试问题")


# ============================================================
# 异常体系测试
# ============================================================

class TestExceptions:
    """异常体系测试。"""

    def test_generation_error_hierarchy(self):
        """GenerationError 是所有生成异常的基类。"""
        assert issubclass(LLMCallError, GenerationError)
        assert issubclass(EmptyRetrievalError, GenerationError)
        assert issubclass(CitationExtractionError, GenerationError)

    def test_llm_call_error_preserves_original(self):
        """LLMCallError 保留原始异常引用。"""
        original = RuntimeError("原始错误")
        error = LLMCallError("LLM 调用失败", original_error=original)

        assert error.original_error is original
        assert "LLM 调用失败" in str(error)

    def test_llm_call_error_without_original(self):
        """LLMCallError 可以不提供 original_error。"""
        error = LLMCallError("LLM 调用失败")
        assert error.original_error is None

    def test_catch_all_with_generation_error(self):
        """所有生成异常可被 GenerationError 统一捕获。"""
        with pytest.raises(GenerationError):
            raise LLMCallError("测试")

        with pytest.raises(GenerationError):
            raise EmptyRetrievalError("测试")

        with pytest.raises(GenerationError):
            raise CitationExtractionError("测试")
