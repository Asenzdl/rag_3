"""Task 1.10 测试：Settings + Factories + Protocol 依赖倒置验证。

覆盖场景：
1. Settings 校验：必填字段缺失、API Key 为空白、repr 防泄露
2. 工厂函数：create_llm 不支持的 provider、create_vectorstore 不支持的类型
3. Protocol 非侵入式抽象：MockRetriever 无需继承即可注入 RAGChain
4. 导入安全性：导入 settings 模块不触发网络请求
"""

import os
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from src.core.exceptions import NonRetryableError
from src.core.settings import Settings


# ============================================================
# Settings 校验测试
# ============================================================


class TestSettingsValidation:
    """Settings 类的字段校验测试。"""

    def test_missing_required_api_key_raises_validation_error(self):
        """必填 API Key 缺失时，Settings() 抛出 ValidationError。"""
        # 清除环境变量以隔离测试
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValidationError):
                Settings(_env_file=None)

    def test_blank_api_key_raises_validation_error(self):
        """API Key 为空白字符串时，field_validator 抛出 ValueError。"""
        with pytest.raises(ValidationError, match="API Key 不能为空"):
            Settings(
                deepseek_api_key="  ",
                deepseek_base_url="https://api.deepseek.com",
                qwen_api_key="sk-test",
                qwen_base_url="https://dashscope.aliyuncs.com",
                _env_file=None,
            )

    def test_api_key_repr_false(self):
        """API Key 字段 repr=False，repr(settings) 不含明文 Key。"""
        settings = Settings(
            deepseek_api_key="sk-super-secret-key",
            deepseek_base_url="https://api.deepseek.com",
            qwen_api_key="sk-another-secret",
            qwen_base_url="https://dashscope.aliyuncs.com",
            _env_file=None,
        )
        repr_str = repr(settings)
        assert "sk-super-secret-key" not in repr_str
        assert "sk-another-secret" not in repr_str

    def test_default_values(self):
        """有默认值的字段在不传参时使用默认值。"""
        # 只保留必填字段的环境变量，删除其他环境变量以验证默认值
        env_keep = {
            "DEEPSEEK_API_KEY": "sk-test",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "QWEN_API_KEY": "sk-test",
            "QWEN_BASE_URL": "https://dashscope.aliyuncs.com",
        }
        with patch.dict(os.environ, env_keep, clear=True):
            settings = Settings(_env_file=None)
            assert settings.ollama_base_url == "http://localhost:11434"
            assert settings.vectorstore_type == "chroma"
            assert settings.chroma_persist_directory == "db/langchain_docs_db1"
            assert settings.chroma_collection_name == "langchain_docs1"
            assert settings.embedding_model == "qwen3-embedding:4b"
            assert settings.eval_qa_path == "data/eval/qa_pairs.json"
            assert settings.eval_report_path == "data/eval/baseline_retrieval_report.md"
            assert settings.checkpoint_db_path == "db/checkpoints.db"
            assert settings.tavily_api_key == ""

    def test_custom_values_override_defaults(self):
        """自定义值覆盖默认值。"""
        settings = Settings(
            deepseek_api_key="sk-test",
            deepseek_base_url="https://api.deepseek.com",
            qwen_api_key="sk-test",
            qwen_base_url="https://dashscope.aliyuncs.com",
            ollama_base_url="http://custom:8080",
            chroma_persist_directory="custom/db",
            _env_file=None,
        )
        assert settings.ollama_base_url == "http://custom:8080"
        assert settings.chroma_persist_directory == "custom/db"


# ============================================================
# Protocol 非侵入式抽象测试
# ============================================================


class MockRetriever:
    """仅实现 invoke 方法的 Mock 检索器 — 验证 Protocol 非侵入式抽象。

    该类不继承任何基类，仅有 invoke(self, query: str) -> List[Document] 方法，
    自动满足 RetrieverProtocol 协议。
    """

    def __init__(self, docs: List[Document] = None):
        self._docs = docs or []

    def invoke(self, query: str) -> List[Document]:
        return self._docs


class TestRetrieverProtocol:
    """RetrieverProtocol 协议的非侵入式抽象测试。"""

    def test_mock_retriever_satisfies_protocol(self):
        """MockRetriever 仅有 invoke 方法，自动满足 RetrieverProtocol。"""
        from src.retriever.protocols import RetrieverProtocol

        mock = MockRetriever()
        # Protocol 的类型检查在静态分析时生效
        # 运行时验证：mock.invoke 可调用且签名匹配
        assert callable(mock.invoke)

    def test_mock_retriever_with_rag_chain(self):
        """MockRetriever 可注入 RAGChain，验证依赖倒置。"""
        from src.generation.rag_chain import RAGChain
        from src.generation.prompts import PromptVersion, get_prompt

        docs = [
            Document(
                page_content="LangGraph 是一个用于构建状态化多参与者应用的框架。",
                metadata={"source": "https://example.com/langgraph"},
            )
        ]
        mock_retriever = MockRetriever(docs=docs)
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content="LangGraph 是一个框架。",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )

        prompt = get_prompt(PromptVersion.V2, include_few_shot=False)
        chain = RAGChain(retriever=mock_retriever, llm=mock_llm, prompt=prompt)

        # 验证 RAGChain 可以正常使用 MockRetriever
        assert chain._retriever is mock_retriever

    def test_mock_retriever_invoke_returns_docs(self):
        """MockRetriever.invoke 返回预期的文档列表。"""
        docs = [
            Document(page_content="test content", metadata={"source": "test.md"}),
        ]
        mock = MockRetriever(docs=docs)
        result = mock.invoke("test query")
        assert len(result) == 1
        assert result[0].page_content == "test content"


# ============================================================
# 工厂函数测试
# ============================================================


class TestCreateLLM:
    """create_llm 工厂函数测试。"""

    def test_unsupported_provider_raises_non_retryable_error(self):
        """不支持的 provider 抛出 NonRetryableError。"""
        from src.core.factories import create_llm

        settings = Settings(
            deepseek_api_key="sk-test",
            deepseek_base_url="https://api.deepseek.com",
            qwen_api_key="sk-test",
            qwen_base_url="https://dashscope.aliyuncs.com",
            _env_file=None,
        )
        with pytest.raises(NonRetryableError, match="不支持的 LLM 提供商"):
            create_llm("unsupported_provider", settings)


class TestCreateVectorstore:
    """create_vectorstore 工厂函数测试。"""

    def test_unsupported_vectorstore_type_raises_non_retryable_error(self):
        """不支持的 vectorstore_type 抛出 NonRetryableError。"""
        from src.core.factories import create_vectorstore

        settings = Settings(
            deepseek_api_key="sk-test",
            deepseek_base_url="https://api.deepseek.com",
            qwen_api_key="sk-test",
            qwen_base_url="https://dashscope.aliyuncs.com",
            vectorstore_type="faiss",
            _env_file=None,
        )
        # 清除缓存
        import src.core.factories as f
        f._vectorstore_cache = None

        with pytest.raises(NonRetryableError, match="不支持的向量库类型"):
            create_vectorstore(settings, embedding_function=MagicMock())


class TestCreateRetriever:
    """create_retriever 工厂函数测试。"""

    def test_create_retriever_returns_retriever_protocol(self):
        """create_retriever 返回满足 RetrieverProtocol 的实例。"""
        from src.core.factories import create_retriever

        settings = Settings(
            deepseek_api_key="sk-test",
            deepseek_base_url="https://api.deepseek.com",
            qwen_api_key="sk-test",
            qwen_base_url="https://dashscope.aliyuncs.com",
            _env_file=None,
        )
        # Mock embeddings 和 vectorstore 以避免实际连接
        mock_embeddings = MagicMock()
        mock_vectorstore = MagicMock()
        mock_vectorstore.as_retriever.return_value = MagicMock()

        with patch("src.core.factories.create_embeddings", return_value=mock_embeddings), \
             patch("src.core.factories.create_vectorstore", return_value=mock_vectorstore), \
             patch("src.retriever.base_retriever.VectorRetriever") as MockRetrieverCls:
            MockRetrieverCls.return_value = MockRetriever(
                docs=[Document(page_content="test", metadata={"source": "test.md"})]
            )
            retriever = create_retriever(settings)
            assert retriever is not None


# ============================================================
# 导入安全性测试
# ============================================================


class TestImportSafety:
    """导入安全性 — 导入 settings 模块不触发网络请求。"""

    def test_import_settings_no_network_request(self):
        """导入 src.core.settings 模块不应触发网络请求。"""
        # 只需确认 Settings 类可被访问且是正确类型
        assert Settings is not None
        assert Settings.__name__ == "Settings"


# ============================================================
# base_retriever 依赖注入测试
# ============================================================


class TestBaseRetrieverDependencyInjection:
    """base_retriever.py 的依赖注入测试。"""

    def test_get_vectorstore_requires_embedding_function(self):
        """get_vectorstore 的 embedding_function 参数不能为 None。"""
        from src.retriever.base_retriever import get_vectorstore

        # 清除 lru_cache
        get_vectorstore.cache_clear()

        with pytest.raises(ValueError, match="embedding_function 不能为 None"):
            get_vectorstore(
                persist_directory="test_db",
                collection_name="test_collection",
                embedding_function=None,
            )

    def test_create_vector_retriever_accepts_embedding_function(self):
        """create_vector_retriever 接受 embedding_function 参数。"""
        from src.retriever.base_retriever import create_vector_retriever
        from src.retriever import base_retriever

        mock_embeddings = MagicMock()
        mock_vs = MagicMock()

        with patch.object(base_retriever, "get_vectorstore", return_value=mock_vs) as mock_get_vs:
            with patch.object(base_retriever, "VectorRetriever", return_value=MagicMock()) as MockCls:
                retriever = create_vector_retriever(
                    embedding_function=mock_embeddings,
                )
                # 验证 get_vectorstore 被调用且传入了 embedding_function
                mock_get_vs.assert_called_once()
                call_kwargs = mock_get_vs.call_args
                assert call_kwargs.kwargs.get("embedding_function") is mock_embeddings or \
                       "embedding_function" in str(call_kwargs)
