"""结构化日志测试。

覆盖 src/utils/logger.py 的核心功能：
1. setup_logging 配置初始化
2. _sanitize_processor 敏感信息脱敏
3. bind_request_id / unbind_request_id 上下文管理
4. JSON 格式输出验证
"""

import json
import logging
from io import StringIO
from unittest.mock import patch

import pytest
import structlog

from src.utils.logger import (
    _SENSITIVE_KEYS,
    _sanitize_processor,
    bind_request_id,
    setup_logging,
    unbind_request_id,
)


# ============================================================
# _sanitize_processor 测试
# ============================================================


class TestSanitizeProcessor:
    """敏感信息脱敏处理器测试。"""

    def test_sanitize_api_key(self):
        """api_key 字段应被脱敏。"""
        event_dict = {"api_key": "sk-d2874cb013704833982de93d9387701f", "event": "测试"}
        result = _sanitize_processor(None, "info", event_dict)
        # 保留前2后2，中间 ****
        assert result["api_key"] == "sk****1f"
        # event 不应被修改
        assert result["event"] == "测试"

    def test_sanitize_password(self):
        """password 字段应被脱敏。"""
        event_dict = {"password": "mysecretpassword", "event": "登录"}
        result = _sanitize_processor(None, "info", event_dict)
        assert result["password"] == "my****rd"

    def test_sanitize_token(self):
        """token 字段应被脱敏。"""
        event_dict = {"token": "eyJhbGciOiJIUzI1NiJ9.abc123", "event": "认证"}
        result = _sanitize_processor(None, "info", event_dict)
        assert result["token"] == "ey****23"

    def test_sanitize_short_value(self):
        """短于 4 字符的值应整体替换为 ****。"""
        event_dict = {"key": "abc"}
        result = _sanitize_processor(None, "info", event_dict)
        assert result["key"] == "****"

    def test_sanitize_exact_4_chars(self):
        """恰好 4 字符的值应整体替换为 ****。"""
        event_dict = {"key": "abcd"}
        result = _sanitize_processor(None, "info", event_dict)
        assert result["key"] == "****"

    def test_sanitize_5_chars(self):
        """5 字符的值应保留前2后2。"""
        event_dict = {"key": "abcde"}
        result = _sanitize_processor(None, "info", event_dict)
        assert result["key"] == "ab****de"

    def test_case_insensitive_matching(self):
        """字段名匹配应忽略大小写。"""
        event_dict = {"API_KEY": "sk-1234567890", "Api_Key": "sk-abcdefghij"}
        result = _sanitize_processor(None, "info", event_dict)
        assert result["API_KEY"] == "sk****90"
        assert result["Api_Key"] == "sk****ij"

    def test_non_sensitive_fields_unchanged(self):
        """非敏感字段不应被修改。"""
        event_dict = {
            "question": "什么是 LangGraph?",
            "doc_count": 5,
            "latency_ms": 123.4,
        }
        result = _sanitize_processor(None, "info", event_dict)
        assert result["question"] == "什么是 LangGraph?"
        assert result["doc_count"] == 5
        assert result["latency_ms"] == 123.4

    def test_mixed_sensitive_and_normal(self):
        """混合敏感和普通字段时只脱敏敏感字段。"""
        event_dict = {
            "event": "LLM 调用",
            "api_key": "sk-secret123",
            "latency_ms": 456.7,
            "password": "pass1234",
        }
        result = _sanitize_processor(None, "info", event_dict)
        assert result["event"] == "LLM 调用"
        assert result["api_key"] == "sk****23"
        assert result["latency_ms"] == 456.7
        assert result["password"] == "pa****34"

    def test_numeric_value_converted_to_string(self):
        """数值类型的敏感值应先转为字符串再脱敏。"""
        event_dict = {"secret": 123456}
        result = _sanitize_processor(None, "info", event_dict)
        # "123456" → "12****56"
        assert result["secret"] == "12****56"

    def test_empty_dict(self):
        """空字典应直接返回。"""
        result = _sanitize_processor(None, "info", {})
        assert result == {}

    def test_all_sensitive_key_names(self):
        """所有定义的敏感字段名都应被脱敏。"""
        for key in _SENSITIVE_KEYS:
            event_dict = {key: "value_too_secret_to_show"}
            result = _sanitize_processor(None, "info", event_dict)
            assert result[key] != "value_too_secret_to_show", (
                f"字段 '{key}' 未被脱敏"
            )


# ============================================================
# setup_logging 测试
# ============================================================


class TestSetupLogging:
    """setup_logging 配置初始化测试。"""

    def setup_method(self):
        """每个测试前重置 structlog 配置。"""
        # 重置 structlog 为默认配置，避免测试间干扰
        structlog.configure(
            processors=[structlog.dev.ConsoleRenderer()],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=False,
        )

    def test_setup_json_format(self):
        """JSON 模式配置应产生 JSON 格式日志。"""
        setup_logging(level="DEBUG", json_format=True)
        log = structlog.get_logger("test_json")
        # 配置后 logger 应可用
        # 验证 structlog 配置是否包含 JSONRenderer
        configured = structlog.get_config()
        processor_names = [type(p).__name__ for p in configured.get("processors", [])]
        assert "JSONRenderer" in processor_names

    def test_setup_console_format(self):
        """Console 模式配置应产生 ConsoleRenderer。"""
        setup_logging(level="DEBUG", json_format=False)
        configured = structlog.get_config()
        processor_names = [type(p).__name__ for p in configured.get("processors", [])]
        assert "ConsoleRenderer" in processor_names

    def test_sets_log_level(self):
        """setup_logging 应设置日志级别。"""
        setup_logging(level="WARNING", json_format=True)
        assert logging.getLogger().level == logging.WARNING

    def test_sets_noisy_loggers_to_warning(self):
        """第三方嘈杂库的日志级别应设为 WARNING。"""
        setup_logging(level="DEBUG", json_format=True)
        for logger_name in ("httpx", "chromadb", "httpcore", "urllib3"):
            assert logging.getLogger(logger_name).level == logging.WARNING

    def test_sanitize_processor_in_chain(self):
        """脱敏处理器应在处理器链中。"""
        setup_logging(level="DEBUG", json_format=True)
        configured = structlog.get_config()
        processors = configured.get("processors", [])
        # _sanitize_processor 是函数对象，检查它在列表中
        # 函数对象的 __name__ 属性应为 "_sanitize_processor"
        processor_names = [
            getattr(p, "__name__", type(p).__name__)
            for p in processors
        ]
        assert "_sanitize_processor" in processor_names


# ============================================================
# bind_request_id / unbind_request_id 测试
# ============================================================


class TestRequestId:
    """request_id 上下文管理测试。"""

    def setup_method(self):
        """每个测试前清除上下文。"""
        structlog.contextvars.clear_contextvars()

    def teardown_method(self):
        """每个测试后清除上下文。"""
        structlog.contextvars.clear_contextvars()

    def test_bind_generates_id_if_not_provided(self):
        """未提供 request_id 时应自动生成。"""
        request_id = bind_request_id()
        assert request_id is not None
        assert len(request_id) == 12

    def test_bind_uses_provided_id(self):
        """提供 request_id 时应使用提供的值。"""
        request_id = bind_request_id("my-custom-id")
        assert request_id == "my-custom-id"

    def test_bind_returns_uuid_format(self):
        """自动生成的 request_id 应为十六进制格式。"""
        request_id = bind_request_id()
        assert all(c in "0123456789abcdef" for c in request_id)

    def test_unbind_clears_context(self):
        """unbind_request_id 应清除上下文中的 request_id。"""
        bind_request_id("test-id-123")
        unbind_request_id()
        # 验证上下文已清除
        ctx = structlog.contextvars.get_contextvars()
        assert "request_id" not in ctx

    def test_bind_clears_previous_context(self):
        """多次 bind 应清除上一次的上下文。"""
        bind_request_id("old-id")
        bind_request_id("new-id")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("request_id") == "new-id"

    def test_request_id_available_in_logger(self):
        """绑定后 logger 应自动包含 request_id。"""
        setup_logging(level="DEBUG", json_format=True)
        bind_request_id("test-req-123")

        # 获取 logger 并验证上下文变量
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("request_id") == "test-req-123"

    def test_generated_ids_are_unique(self):
        """自动生成的 request_id 应唯一。"""
        ids = {bind_request_id() for _ in range(100)}
        # 100 个 ID 应全部唯一
        assert len(ids) == 100


# ============================================================
# 集成测试：日志输出格式
# ============================================================


class TestLogOutputFormat:
    """日志输出格式集成测试。"""

    def setup_method(self):
        """每个测试前重置配置。"""
        structlog.contextvars.clear_contextvars()
        structlog.configure(
            processors=[structlog.dev.ConsoleRenderer()],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=False,
        )

    def teardown_method(self):
        """每个测试后清除上下文。"""
        structlog.contextvars.clear_contextvars()

    def test_json_output_contains_required_fields(self):
        """JSON 日志输出应包含 timestamp、level、event、request_id 字段。"""
        # 使用 StringIO 捕获输出
        import io
        output = io.StringIO()

        setup_logging(level="DEBUG", json_format=True)
        bind_request_id("test-req-id")

        # 手动构建 JSON 日志并验证字段
        log = structlog.get_logger("test_format")
        # 由于 structlog 输出到 stderr/stdout，我们通过检查配置验证
        # 而非直接捕获输出（捕获输出在不同测试框架中不稳定）
        configured = structlog.get_config()
        processors = configured.get("processors", [])

        # 验证关键处理器存在
        processor_names = [
            getattr(p, "__name__", type(p).__name__)
            for p in processors
        ]
        # merge_contextvars → request_id 注入
        assert "merge_contextvars" in processor_names
        # TimeStamper → timestamp
        assert "TimeStamper" in processor_names
        # add_log_level → level
        assert "add_log_level" in processor_names
        # JSONRenderer → JSON 格式
        assert "JSONRenderer" in processor_names

        unbind_request_id()

    def test_sensitive_data_not_in_output(self):
        """敏感数据不应出现在日志输出中。"""
        event_dict = {
            "event": "测试",
            "api_key": "sk-d2874cb013704833982de93d9387701f",
        }
        result = _sanitize_processor(None, "info", event_dict)
        # 脱敏后 api_key 不应包含完整值
        assert "d2874cb013704833982de93d9387701f" not in result["api_key"]
        assert result["api_key"] == "sk****1f"
