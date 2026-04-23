"""Task 1.8 端到端测试：CLI 交互入口与 RAG 链路集成验证。

测试策略：
    完全 Mock RAGChain 的 invoke/stream/retrieve/extract_citations 方法，
    不依赖外部网络和本地向量库，保证测试独立性和稳定性。

    真正的集成验证留给手动 `python src/app.py` 运行。

测试覆盖：
    1. ChatSession 单元测试（add/trim/clear/get_history）
    2. format_sources / format_citations 纯函数测试
    3. cli_loop 集成测试（正常问答、退出、异常处理）
    4. main() 初始化测试（RAGChain 创建成功/失败）
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.app import (
    ChatSession,
    _EXIT_COMMANDS,
    _GOODBYE_MESSAGE,
    _SEPARATOR,
    _WELCOME_MESSAGE,
    cli_loop,
    format_citations,
    format_sources,
    main,
)
from src.core.exceptions import RAGSystemError
from src.generation.citation_chain import ValidatedCitation
from src.generation.exceptions import GenerationError, LLMCallError
from src.generation.rag_chain import RAGResponse


# ============================================================
# Fixtures
# ============================================================

# 评估数据集路径
QA_PAIRS_PATH = Path(__file__).parent.parent / "data" / "eval" / "qa_pairs.json"


@pytest.fixture
def qa_pairs():
    """加载评估数据集中的 QA pairs。

    为什么从文件加载而非硬编码：
        保证测试数据与评估数据集一致，修改数据集后测试自动同步。
    """
    with open(QA_PAIRS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def mock_chain():
    """创建 Mock RAGChain 实例。

    设计意图：
        Mock 掉所有外部依赖（LLM、向量库），使测试完全独立。
        stream() 返回生成器，模拟逐 token 输出。
        retrieve() 返回带 source 的文档列表。
        extract_citations() 返回验证后的引用列表。
    """
    chain = MagicMock(spec=["stream", "invoke", "retrieve", "extract_citations"])

    # stream() 返回生成器（模拟逐 token 输出）
    def mock_stream(question):
        yield "LangGraph"
        yield " 是"
        yield " 一个"
        yield " 构建多演员应用的框架。"

    chain.stream = MagicMock(side_effect=mock_stream)

    # invoke() 返回 RAGResponse
    chain.invoke = MagicMock(
        return_value=RAGResponse(
            answer="LangGraph 是一个构建多演员应用的框架。",
            sources=["https://docs.langchain.com/oss/python/langgraph/overview"],
            citations=[
                ValidatedCitation(number=1, url="https://docs.langchain.com/oss/python/langgraph/overview", is_valid=True)
            ],
            retrieval_count=3,
        )
    )

    # retrieve() 返回文档列表
    chain.retrieve = MagicMock(
        return_value=[
            Document(
                page_content="LangGraph 是一个构建多演员应用的框架。",
                metadata={"source": "https://docs.langchain.com/oss/python/langgraph/overview"},
            ),
            Document(
                page_content="LangGraph 支持状态管理和条件边。",
                metadata={"source": "https://docs.langchain.com/oss/python/langgraph/use-graph-api"},
            ),
            Document(
                page_content="LangGraph 提供持久化功能。",
                metadata={"source": "https://docs.langchain.com/oss/python/langgraph/persistence"},
            ),
        ]
    )

    # extract_citations() 返回引用验证结果
    chain.extract_citations = MagicMock(
        return_value=[
            ValidatedCitation(
                number=1,
                url="https://docs.langchain.com/oss/python/langgraph/overview",
                is_valid=True,
            )
        ]
    )

    return chain


@pytest.fixture
def session():
    """创建 ChatSession 实例。"""
    return ChatSession(max_turns=10)


# ============================================================
# ChatSession 单元测试
# ============================================================


class TestChatSession:
    """ChatSession 类的单元测试。"""

    def test_add_user_message(self, session):
        """测试添加用户消息。"""
        session.add_user_message("你好")

        # 验证 history 中添加了 HumanMessage
        assert len(session._history) == 1
        assert isinstance(session._history[0], HumanMessage)
        assert session._history[0].content == "你好"
        # turn_count 应为 1
        assert session.turn_count == 1

    def test_add_ai_message(self, session):
        """测试添加 AI 回复。"""
        session.add_user_message("你好")
        session.add_ai_message("你好！有什么可以帮助你的？")

        # 验证 history 中有 2 条消息
        assert len(session._history) == 2
        assert isinstance(session._history[1], AIMessage)
        assert session._history[1].content == "你好！有什么可以帮助你的？"
        # turn_count 仍为 1（一轮 = 1 Human + 1 AI）
        assert session.turn_count == 1

    def test_get_history_returns_copy(self, session):
        """测试 get_history() 返回的是副本而非引用。"""
        session.add_user_message("测试")
        history = session.get_history()

        # 修改返回值不影响内部状态
        history.append(HumanMessage(content="不应出现"))
        assert len(session._history) == 1

    def test_clear(self, session):
        """测试清空会话。"""
        session.add_user_message("问题1")
        session.add_ai_message("回答1")
        session.clear()

        assert len(session._history) == 0
        assert session.turn_count == 0

    def test_trim_on_max_turns(self):
        """测试超过最大轮数时自动裁剪。"""
        session = ChatSession(max_turns=2)

        # 添加 3 轮对话
        for i in range(3):
            session.add_user_message(f"问题{i + 1}")
            session.add_ai_message(f"回答{i + 1}")

        # max_turns=2，所以最多保留 2*2=4 条消息
        # 第 3 轮 add_user_message 时触发 trim，移除第 1 轮
        assert len(session._history) == 4  # 2 轮 * 2 条
        assert session.turn_count == 3  # turn_count 不因 trim 减小

    def test_trim_keeps_latest_messages(self):
        """测试裁剪保留最新消息。"""
        session = ChatSession(max_turns=1)

        session.add_user_message("旧问题")
        session.add_ai_message("旧回答")
        session.add_user_message("新问题")
        session.add_ai_message("新回答")

        # max_turns=1，第 2 轮 add_user_message 时移除第 1 轮
        # 最终只剩 1 轮 = 4 条消息（因为 add_ai_message 不触发 trim）
        # 实际：add_user_message("新问题") 时 history 有 3 条（> 1*2=2），trim 移除前 2 条
        # 然后 add_ai_message("新回答") 添加 1 条，总共 2 条
        assert len(session._history) == 2
        assert session._history[0].content == "新问题"
        assert session._history[1].content == "新回答"

    def test_empty_history(self, session):
        """测试初始空历史。"""
        assert session.get_history() == []
        assert session.turn_count == 0

    def test_multiple_turns_sequential(self, session):
        """测试多轮对话的 history 累积。"""
        for i in range(5):
            session.add_user_message(f"问题{i + 1}")
            session.add_ai_message(f"回答{i + 1}")

        assert len(session._history) == 10  # 5 轮 * 2 条
        assert session.turn_count == 5


# ============================================================
# format_sources 测试
# ============================================================


class TestFormatSources:
    """format_sources 纯函数测试。"""

    def test_empty_sources(self):
        """空列表返回空字符串。"""
        assert format_sources([]) == ""

    def test_single_source(self):
        """单条来源格式化正确。"""
        result = format_sources(["https://example.com/doc1"])
        assert "📚 来源：" in result
        assert "[1] https://example.com/doc1" in result

    def test_multiple_sources(self):
        """多条来源编号正确。"""
        sources = [
            "https://example.com/doc1",
            "https://example.com/doc2",
            "https://example.com/doc3",
        ]
        result = format_sources(sources)
        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" in result

    def test_deduplication_preserves_order(self):
        """去重保持原始顺序。"""
        sources = [
            "https://example.com/doc1",
            "https://example.com/doc2",
            "https://example.com/doc1",  # 重复
        ]
        result = format_sources(sources)
        # doc1 只出现一次
        assert result.count("https://example.com/doc1") == 1
        # doc2 仍然在第二位
        lines = result.split("\n")
        assert "doc1" in lines[1]
        assert "doc2" in lines[2]


# ============================================================
# format_citations 测试
# ============================================================


class TestFormatCitations:
    """format_citations 纯函数测试。"""

    def test_empty_citations(self):
        """空列表返回空字符串。"""
        assert format_citations([]) == ""

    def test_valid_citation(self):
        """有效引用显示 ✅。"""
        citations = [
            ValidatedCitation(number=1, url="https://example.com/doc1", is_valid=True)
        ]
        result = format_citations(citations)
        assert "✅ 引用验证：" in result
        assert "[1] ✅ https://example.com/doc1" in result

    def test_invalid_citation(self):
        """无效引用显示 ❌。"""
        citations = [
            ValidatedCitation(number=2, url="https://invalid.com", is_valid=False)
        ]
        result = format_citations(citations)
        assert "[2] ❌ https://invalid.com" in result

    def test_mixed_citations(self):
        """混合有效/无效引用。"""
        citations = [
            ValidatedCitation(number=1, url="https://example.com/doc1", is_valid=True),
            ValidatedCitation(number=2, url="https://invalid.com", is_valid=False),
        ]
        result = format_citations(citations)
        assert "✅" in result
        assert "❌" in result


# ============================================================
# cli_loop 集成测试
# ============================================================


class TestCliLoop:
    """cli_loop 函数的集成测试。

    使用 unittest.mock.patch 替换 input()，模拟用户输入。
    """

    def test_exit_command(self, mock_chain, session, capsys):
        """输入 exit 能正常退出。"""
        with patch("builtins.input", return_value="exit"):
            cli_loop(mock_chain, session)

        output = capsys.readouterr().out
        assert _GOODBYE_MESSAGE in output

    def test_quit_command(self, mock_chain, session, capsys):
        """输入 quit 能正常退出。"""
        with patch("builtins.input", return_value="quit"):
            cli_loop(mock_chain, session)

        output = capsys.readouterr().out
        assert _GOODBYE_MESSAGE in output

    def test_case_insensitive_exit(self, mock_chain, session, capsys):
        """exit/quit 不区分大小写。"""
        with patch("builtins.input", return_value="EXIT"):
            cli_loop(mock_chain, session)

        output = capsys.readouterr().out
        assert _GOODBYE_MESSAGE in output

    def test_single_question(self, mock_chain, session, capsys):
        """单轮问答：输入问题 → 获取回答 → 显示来源 → 退出。"""
        # 模拟用户输入：先问一个问题，再输入 exit
        inputs = iter(["LangGraph 是什么？", "exit"])

        with patch("builtins.input", side_effect=inputs):
            cli_loop(mock_chain, session)

        output = capsys.readouterr().out

        # 验证欢迎信息
        assert "RAG 问答系统" in output
        # 验证流式输出（stream mock 返回 "LangGraph 是一个构建多演员应用的框架。"）
        assert "LangGraph" in output
        # 验证来源显示
        assert "📚 来源：" in output
        # 验证引用验证
        assert "✅ 引用验证：" in output
        # 验证告别信息
        assert _GOODBYE_MESSAGE in output
        # 验证 session 中有对话历史
        assert session.turn_count == 1

    def test_empty_input_ignored(self, mock_chain, session, capsys):
        """空行输入被忽略，不触发 RAGChain 调用。"""
        inputs = iter(["", "   ", "exit"])

        with patch("builtins.input", side_effect=inputs):
            cli_loop(mock_chain, session)

        # stream/invoke 不应被调用
        mock_chain.stream.assert_not_called()
        mock_chain.invoke.assert_not_called()

    def test_keyboard_interrupt(self, mock_chain, session, capsys):
        """Ctrl+C 触发 KeyboardInterrupt 能优雅退出。"""
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            cli_loop(mock_chain, session)

        output = capsys.readouterr().out
        assert _GOODBYE_MESSAGE in output

    def test_eof_error(self, mock_chain, session, capsys):
        """EOFError（Ctrl+D / Ctrl+Z+Enter）能优雅退出。"""
        with patch("builtins.input", side_effect=EOFError):
            cli_loop(mock_chain, session)

        output = capsys.readouterr().out
        assert _GOODBYE_MESSAGE in output

    def test_rag_system_error_continues(self, mock_chain, session, capsys):
        """RAGSystemError 不中断 REPL，继续等待下一个问题。"""
        # 让 stream() 和 invoke() 都抛出 RAGSystemError
        # 这样错误才能传播到外层的 RAGSystemError 捕获
        mock_chain.stream = MagicMock(
            side_effect=GenerationError("LLM 调用失败")
        )
        mock_chain.invoke = MagicMock(
            side_effect=LLMCallError("LLM 调用失败", is_retryable=False)
        )
        # retrieve 也抛异常（因为 invoke 异常后不会到达 retrieve）
        mock_chain.retrieve = MagicMock(
            side_effect=GenerationError("检索失败")
        )

        inputs = iter(["LangGraph 是什么？", "exit"])

        with patch("builtins.input", side_effect=inputs):
            cli_loop(mock_chain, session)

        output = capsys.readouterr().out
        # 验证错误信息被显示
        assert "❌ 系统错误" in output
        # 验证告别信息出现（说明循环没被中断）
        assert _GOODBYE_MESSAGE in output

    def test_multiple_turns(self, mock_chain, session, capsys):
        """多轮问答：连续 5 轮问答后退出。"""
        questions = [f"问题{i + 1}" for i in range(5)] + ["exit"]
        inputs = iter(questions)

        with patch("builtins.input", side_effect=inputs):
            cli_loop(mock_chain, session)

        # 验证 5 轮问答
        assert session.turn_count == 5
        assert len(session._history) == 10  # 5 HumanMessage + 5 AIMessage

    def test_irrelevant_question(self, mock_chain, session, capsys):
        """与文档无关的问题（空检索结果）不崩溃。"""
        # 模拟空检索
        mock_chain.stream = MagicMock(
            side_effect=iter(["抱歉，我在文档库中未找到与您问题相关的内容。"])
        )
        mock_chain.retrieve = MagicMock(return_value=[])
        mock_chain.extract_citations = MagicMock(return_value=[])

        inputs = iter(["今天天气怎么样？", "exit"])

        with patch("builtins.input", side_effect=inputs):
            cli_loop(mock_chain, session)

        output = capsys.readouterr().out
        # 验证空检索预设回复被显示
        assert "未找到" in output
        # 验证无来源显示（因为 retrieve 返回空列表）
        assert "📚 来源：" not in output
        # 验证程序没崩溃
        assert _GOODBYE_MESSAGE in output


# ============================================================
# E2E 测试：使用 qa_pairs 数据集
# ============================================================


class TestE2EWithQAPairs:
    """使用评估数据集的端到端测试。

    完全 Mock RAGChain，验证 CLI 层能正确处理数据集中的问题。

    验收标准：
        - 5 个测试用例对应 qa_pairs.json 中的前 5 个问题
        - 每个用例验证：非空回答 + 来源信息显示
        - 不依赖特定 API 响应内容（仅验证非空字符串和格式）
    """

    def _create_mock_chain_for_question(self, question: str, qa_item: dict) -> MagicMock:
        """为特定问题创建定制 Mock chain。

        为什么每个问题需要独立 Mock：
            不同问题的来源和回答不同，需要定制 Mock 返回值
            以验证 CLI 对不同数据的正确处理。
        """
        chain = MagicMock(spec=["stream", "invoke", "retrieve", "extract_citations"])

        # 构建模拟回答
        answer = f"这是关于 {question[:20]} 的回答。"
        sources = qa_item.get("expected_sources", [])

        # stream() 返回生成器
        def mock_stream(q):
            for word in answer:
                yield word

        chain.stream = MagicMock(side_effect=mock_stream)
        chain.invoke = MagicMock(
            return_value=RAGResponse(
                answer=answer,
                sources=sources,
                citations=[
                    ValidatedCitation(number=i + 1, url=s, is_valid=True)
                    for i, s in enumerate(sources)
                ],
                retrieval_count=len(sources),
            )
        )

        # retrieve() 返回带 source 的文档
        chain.retrieve = MagicMock(
            return_value=[
                Document(
                    page_content=f"文档内容 {i + 1}",
                    metadata={"source": s},
                )
                for i, s in enumerate(sources)
            ]
        )

        # extract_citations() 返回验证结果
        chain.extract_citations = MagicMock(
            return_value=[
                ValidatedCitation(number=i + 1, url=s, is_valid=True)
                for i, s in enumerate(sources)
            ]
        )

        return chain

    def test_q001_langgraph_overview(self, qa_pairs, capsys):
        """问题 1：LangGraph 是什么？"""
        qa_item = qa_pairs[0]
        chain = self._create_mock_chain_for_question(qa_item["question"], qa_item)
        session = ChatSession()

        inputs = iter([qa_item["question"], "exit"])
        with patch("builtins.input", side_effect=inputs):
            cli_loop(chain, session)

        output = capsys.readouterr().out
        # 验证非空回答
        assert len(output) > 0
        # 验证来源显示
        assert "📚 来源：" in output
        # 验证 session 记录
        assert session.turn_count == 1

    def test_q002_state_definition(self, qa_pairs, capsys):
        """问题 2：如何在 LangGraph 中定义和更新状态？"""
        qa_item = qa_pairs[1]
        chain = self._create_mock_chain_for_question(qa_item["question"], qa_item)
        session = ChatSession()

        inputs = iter([qa_item["question"], "exit"])
        with patch("builtins.input", side_effect=inputs):
            cli_loop(chain, session)

        output = capsys.readouterr().out
        assert len(output) > 0
        assert "📚 来源：" in output

    def test_q003_reducer(self, qa_pairs, capsys):
        """问题 3：什么是 reducer？"""
        qa_item = qa_pairs[2]
        chain = self._create_mock_chain_for_question(qa_item["question"], qa_item)
        session = ChatSession()

        inputs = iter([qa_item["question"], "exit"])
        with patch("builtins.input", side_effect=inputs):
            cli_loop(chain, session)

        output = capsys.readouterr().out
        assert len(output) > 0
        assert "📚 来源：" in output

    def test_q004_conditional_edges(self, qa_pairs, capsys):
        """问题 4：如何创建条件边？"""
        qa_item = qa_pairs[3]
        chain = self._create_mock_chain_for_question(qa_item["question"], qa_item)
        session = ChatSession()

        inputs = iter([qa_item["question"], "exit"])
        with patch("builtins.input", side_effect=inputs):
            cli_loop(chain, session)

        output = capsys.readouterr().out
        assert len(output) > 0
        assert "📚 来源：" in output

    def test_q005_persistence(self, qa_pairs, capsys):
        """问题 5：持久化功能有什么作用？"""
        qa_item = qa_pairs[4]
        chain = self._create_mock_chain_for_question(qa_item["question"], qa_item)
        session = ChatSession()

        inputs = iter([qa_item["question"], "exit"])
        with patch("builtins.input", side_effect=inputs):
            cli_loop(chain, session)

        output = capsys.readouterr().out
        assert len(output) > 0
        assert "📚 来源：" in output


# ============================================================
# main() 初始化测试
# ============================================================


class TestMain:
    """main() 函数的测试。"""

    @patch("src.app.RAGChain")
    @patch("src.app.setup_logging")
    @patch("src.app.load_dotenv")
    def test_main_success(self, mock_dotenv, mock_setup_logging, mock_ragchain_class, capsys):
        """main() 正常初始化并启动 REPL。"""
        # Mock RAGChain.create() 返回实例
        mock_chain = MagicMock()
        mock_ragchain_class.create.return_value = mock_chain

        # Mock cli_loop 通过 input 触发立即退出
        with patch("builtins.input", side_effect=EOFError):
            main()

        # 验证 load_dotenv 被调用
        mock_dotenv.assert_called_once_with(override=True)
        # 验证 setup_logging 被调用
        mock_setup_logging.assert_called_once_with(level="INFO", json_format=False)
        # 验证 RAGChain.create() 被调用
        mock_ragchain_class.create.assert_called_once()

    @patch("src.app.RAGChain")
    @patch("src.app.setup_logging")
    @patch("src.app.load_dotenv")
    def test_main_init_failure(self, mock_dotenv, mock_setup_logging, mock_ragchain_class):
        """main() 初始化失败时以非零状态码退出。"""
        # Mock RAGChain.create() 抛出 RAGSystemError
        mock_ragchain_class.create.side_effect = RAGSystemError("向量库不存在")

        with pytest.raises(SystemExit) as exc_info:
            main()

        # 验证退出码为 1
        assert exc_info.value.code == 1


# ============================================================
# 退出命令常量测试
# ============================================================


class TestExitCommands:
    """退出命令相关常量测试。"""

    def test_exit_commands_contains_expected(self):
        """退出命令集合包含 exit 和 quit。"""
        assert "exit" in _EXIT_COMMANDS
        assert "quit" in _EXIT_COMMANDS

    def test_welcome_message_content(self):
        """欢迎信息包含必要提示。"""
        assert "exit" in _WELCOME_MESSAGE or "quit" in _WELCOME_MESSAGE

    def test_goodbye_message_content(self):
        """告别信息不为空。"""
        assert len(_GOODBYE_MESSAGE) > 0
