"""统一异常体系测试。

覆盖 src/core/exceptions.py 的异常继承关系，
以及 src/generation/exceptions.py 和 src/retriever/base_retriever.py
的异常与 RAGSystemError 的兼容性。
"""

import pytest

from src.core.exceptions import (
    NonRetryableError,
    RAGSystemError,
    RetryableError,
)
from src.generation.exceptions import (
    CitationExtractionError,
    EmptyRetrievalError,
    GenerationError,
    LLMCallError,
)
from src.retriever.base_retriever import (
    RetrievalError,
    UnsupportedSearchTypeError,
)


# ============================================================
# RAGSystemError 基类测试
# ============================================================


class TestRAGSystemError:
    """RAGSystemError 公共基类测试。"""

    def test_is_exception_subclass(self):
        """RAGSystemError 应该是 Exception 的子类。"""
        assert issubclass(RAGSystemError, Exception)

    def test_can_be_raised_and_caught(self):
        """RAGSystemError 可以被抛出和捕获。"""
        with pytest.raises(RAGSystemError):
            raise RAGSystemError("测试异常")

    def test_message_preserved(self):
        """异常消息应被保留。"""
        error = RAGSystemError("系统异常")
        assert str(error) == "系统异常"


# ============================================================
# RetryableError / NonRetryableError 标记基类测试
# ============================================================


class TestRetryableError:
    """RetryableError 标记基类测试。"""

    def test_is_rag_system_error_subclass(self):
        """RetryableError 应该是 RAGSystemError 的子类。"""
        assert issubclass(RetryableError, RAGSystemError)

    def test_isinstance_check(self):
        """RetryableError 实例应通过 isinstance 检查。"""
        error = RetryableError("可重试错误")
        assert isinstance(error, RAGSystemError)
        assert isinstance(error, RetryableError)

    def test_can_be_caught_as_rag_system_error(self):
        """RetryableError 应被 RAGSystemError 捕获。"""
        with pytest.raises(RAGSystemError):
            raise RetryableError("可重试")


class TestNonRetryableError:
    """NonRetryableError 标记基类测试。"""

    def test_is_rag_system_error_subclass(self):
        """NonRetryableError 应该是 RAGSystemError 的子类。"""
        assert issubclass(NonRetryableError, RAGSystemError)

    def test_isinstance_check(self):
        """NonRetryableError 实例应通过 isinstance 检查。"""
        error = NonRetryableError("不可重试错误")
        assert isinstance(error, RAGSystemError)
        assert isinstance(error, NonRetryableError)


# ============================================================
# GenerationError 继承关系测试
# ============================================================


class TestGenerationErrorHierarchy:
    """GenerationError 继承关系测试。"""

    def test_generation_error_inherits_rag_system_error(self):
        """GenerationError 应继承 RAGSystemError。"""
        assert issubclass(GenerationError, RAGSystemError)

    def test_generation_error_can_be_caught_as_rag_system_error(self):
        """GenerationError 应被 RAGSystemError 捕获。"""
        with pytest.raises(RAGSystemError):
            raise GenerationError("生成失败")

    def test_llm_call_error_inherits_generation_error(self):
        """LLMCallError 应继承 GenerationError。"""
        assert issubclass(LLMCallError, GenerationError)

    def test_llm_call_error_inherits_rag_system_error(self):
        """LLMCallError 应继承 RAGSystemError（通过 GenerationError）。"""
        assert issubclass(LLMCallError, RAGSystemError)

    def test_llm_call_error_is_retryable_attribute(self):
        """LLMCallError 应有 is_retryable 属性，默认 True。"""
        error = LLMCallError("调用失败")
        assert error.is_retryable is True

    def test_llm_call_error_is_retryable_false(self):
        """LLMCallError 可显式设置 is_retryable=False。"""
        error = LLMCallError("认证失败", is_retryable=False)
        assert error.is_retryable is False

    def test_llm_call_error_original_error(self):
        """LLMCallError 应保存原始异常。"""
        original = ValueError("底层错误")
        error = LLMCallError("包装错误", original_error=original)
        assert error.original_error is original

    def test_empty_retrieval_error_inherits_non_retryable(self):
        """EmptyRetrievalError 应同时继承 NonRetryableError。"""
        assert issubclass(EmptyRetrievalError, GenerationError)
        assert issubclass(EmptyRetrievalError, NonRetryableError)
        assert issubclass(EmptyRetrievalError, RAGSystemError)

    def test_empty_retrieval_error_is_non_retryable(self):
        """EmptyRetrievalError 实例应通过 NonRetryableError isinstance 检查。"""
        error = EmptyRetrievalError("空检索")
        assert isinstance(error, NonRetryableError)

    def test_citation_extraction_error_inherits_non_retryable(self):
        """CitationExtractionError 应同时继承 NonRetryableError。"""
        assert issubclass(CitationExtractionError, GenerationError)
        assert issubclass(CitationExtractionError, NonRetryableError)

    def test_citation_extraction_error_is_non_retryable(self):
        """CitationExtractionError 实例应通过 NonRetryableError isinstance 检查。"""
        error = CitationExtractionError("提取失败")
        assert isinstance(error, NonRetryableError)


# ============================================================
# RetrievalError 继承关系测试
# ============================================================


class TestRetrievalErrorHierarchy:
    """RetrievalError 继承关系测试。"""

    def test_retrieval_error_inherits_rag_system_error(self):
        """RetrievalError 应继承 RAGSystemError。"""
        assert issubclass(RetrievalError, RAGSystemError)

    def test_retrieval_error_can_be_caught_as_rag_system_error(self):
        """RetrievalError 应被 RAGSystemError 捕获。"""
        with pytest.raises(RAGSystemError):
            raise RetrievalError("检索失败")

    def test_unsupported_search_type_error_inherits_non_retryable(self):
        """UnsupportedSearchTypeError 应同时继承 NonRetryableError。"""
        assert issubclass(UnsupportedSearchTypeError, RetrievalError)
        assert issubclass(UnsupportedSearchTypeError, NonRetryableError)
        assert issubclass(UnsupportedSearchTypeError, RAGSystemError)

    def test_unsupported_search_type_error_is_non_retryable(self):
        """UnsupportedSearchTypeError 实例应通过 NonRetryableError isinstance 检查。"""
        error = UnsupportedSearchTypeError("不支持的搜索类型")
        assert isinstance(error, NonRetryableError)


# ============================================================
# 统一捕获测试
# ============================================================


class TestUnifiedCatch:
    """统一捕获所有系统异常测试。"""

    def test_catch_all_generation_errors(self):
        """RAGSystemError 应捕获所有 GenerationError 子类。"""
        errors = [
            GenerationError("基类错误"),
            LLMCallError("调用失败"),
            EmptyRetrievalError("空检索"),
            CitationExtractionError("引用失败"),
        ]
        for error in errors:
            with pytest.raises(RAGSystemError):
                raise error

    def test_catch_all_retrieval_errors(self):
        """RAGSystemError 应捕获所有 RetrievalError 子类。"""
        errors = [
            RetrievalError("检索失败"),
            UnsupportedSearchTypeError("不支持的类型"),
        ]
        for error in errors:
            with pytest.raises(RAGSystemError):
                raise error

    def test_catch_retryable_and_non_retryable(self):
        """RAGSystemError 应捕获 RetryableError 和 NonRetryableError。"""
        with pytest.raises(RAGSystemError):
            raise RetryableError("可重试")

        with pytest.raises(RAGSystemError):
            raise NonRetryableError("不可重试")

    def test_generation_and_retrieval_errors_are_not_causeach_other(self):
        """GenerationError 和 RetrievalError 不应有继承关系。"""
        # GenerationError 不是 RetrievalError 的子类
        assert not issubclass(GenerationError, RetrievalError)
        # RetrievalError 不是 GenerationError 的子类
        assert not issubclass(RetrievalError, GenerationError)
        # 但两者都是 RAGSystemError 的子类
        assert issubclass(GenerationError, RAGSystemError)
        assert issubclass(RetrievalError, RAGSystemError)
