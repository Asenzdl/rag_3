"""CLI 交互入口（Phase 2 LangGraph 版）：REPL 问答 + 流式输出 + 会话管理。

核心设计：
1. **LangGraph 工作流**：通过 build_graph + create_checkpointer 构建图，
   替代 Phase 1 的 RAGChain。图内部管理检索、路由、生成全流程。

2. **流式输出**：使用 graph.stream(version="v2", stream_mode="messages")
   逐 token 输出 generate 节点的回答，实现打字机效果。
   通过 metadata["langgraph_node"] 过滤仅显示 generate 节点输出。

3. **会话管理**：SessionInfo 封装 thread_id + config，checkpointer
   自动管理对话历史。与 Phase 1 的 ChatSession._history（持有数据）
   不同，SessionInfo.thread_id 只持有引用——"持有引用"而非"持有数据"。

4. **优雅退出**：捕获 KeyboardInterrupt / EOFError，打印告别信息 + thread_id
   恢复提示，确保用户能用 --thread-id 恢复会话。

5. **容错**：业务异常不中断 REPL；stream 异常回退 invoke；初始化异常退出。

使用方式：
    # 默认启动（新会话 + 流式输出）
    python src/app.py

    # 恢复已有会话
    python src/app.py --thread-id abc12345

    # 关闭流式
    python src/app.py --no-stream
"""

import argparse
import io
import sys
import uuid
from dataclasses import dataclass
from typing import List

import structlog
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from src.core.config import settings
from src.core.exceptions import RAGSystemError
from src.utils.logger import setup_logging
from src.workflow.builder import build_graph
from src.workflow.checkpointer import create_checkpointer
from src.workflow.state import GraphContext

logger = structlog.get_logger(__name__)


# ============================================================
# 常量
# ============================================================

_EXIT_COMMANDS = {"exit", "quit"}
"""退出命令集合（不区分大小写）。"""

_STREAM_OUTPUT_NODES = {"generate"}
"""流式输出允许的节点集合 — 仅 generate 节点的 token 输出到终端。
为什么用集合而非单字符串：未来如果 greeting/fallback 也用 LLM 生成，扩展只需加元素。"""

_WELCOME_MESSAGE = """========================================
🤖 RAG 问答系统 v2.0（Phase 2 LangGraph 版）
输入问题开始对话，输入 exit/quit 退出
========================================"""

_GOODBYE_MESSAGE = "👋 感谢使用，再见！"

_RESUME_HINT = "💡 恢复会话：python src/app.py --thread-id {thread_id}"

_SEPARATOR = "—" * 40


# ============================================================
# SessionInfo — Phase 2 会话元数据
# ============================================================


@dataclass
class SessionInfo:
    """Phase 2 CLI 会话元数据 — 仅持有 handle，不持有数据。

    设计意图：
        Phase 1 的 ChatSession._history 持有数据本身（List[BaseMessage]），
        Phase 2 的 SessionInfo.thread_id 持有数据的引用（checkpointer 中的键）。
        这是从"持有数据"到"持有引用"的架构升级——类比 ORM 对象 vs 外键引用。

    为什么 turn_count 不独立维护：
        checkpointer 已管理 messages，turn_count 可从
        len([m for m in state["messages"] if isinstance(m, HumanMessage)]) 推导。
        独立维护会在 KeyboardInterrupt 后产生数据不一致
        （turn_count 已 +1 但 messages 未持久化到当前轮）。
    """

    thread_id: str
    config: dict

    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.config = {"configurable": {"thread_id": thread_id}}


# ============================================================
# CLI 参数解析
# ============================================================


def parse_args() -> argparse.Namespace:
    """解析 CLI 参数。

    为什么用 argparse 而非 click/typer：
        项目无 CLI 框架依赖，argparse 是标准库零依赖方案。
        Phase 5 FastAPI 服务化后 CLI 参数可能不再需要，
        不值得为临时性 CLI 引入第三方框架。

    参数优先级：CLI 参数 > 环境变量 > settings.py 默认值
    """
    parser = argparse.ArgumentParser(description="RAG 问答系统（Phase 2 LangGraph 版）")
    parser.add_argument(
        "--thread-id",
        type=str,
        default=None,
        help="恢复已有会话（传入之前的 thread_id），不传则自动生成新会话",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        default=False,
        help="关闭流式输出，回退到 invoke 模式",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="启用 DEBUG 日志 + stream_mode=['messages','updates'] 显示节点状态",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4000,
        help="覆写 GraphContext.max_tokens（memory 触发阈值），默认 4000",
    )
    return parser.parse_args()


# ============================================================
# 格式化辅助函数
# ============================================================


def format_sources(sources: List[str]) -> str:
    """将来源 URL 列表格式化为可读字符串。

    Args:
        sources: 来源 URL 列表（可能有重复）

    Returns:
        格式化后的字符串，空列表返回空字符串。
    """
    if not sources:
        return ""

    unique_sources = list(dict.fromkeys(sources))
    lines = [f"  [{i}] {url}" for i, url in enumerate(unique_sources, 1)]
    return "📚 来源：\n" + "\n".join(lines)


def _extract_sources(state_values: dict) -> list[str]:
    """从图状态中提取来源 URL 列表。

    为什么独立为函数：
        流式和非流式模式都需要从状态取来源，但取入口不同：
        流式 = get_state(config).values，非流式 = result.value。
        抽取为函数统一入口，避免两套提取逻辑。
    """
    documents = state_values.get("documents", [])
    return [doc.metadata.get("source", "") for doc in documents if doc.metadata.get("source")]


# ============================================================
# 流式输出核心
# ============================================================


def _stream_response(
    graph,
    input_state: dict,
    session: SessionInfo,
    graph_context: GraphContext,
    debug: bool = False,
) -> str:
    """流式输出核心 — 逐 token 显示 generate 节点的回答。

    为什么 version="v2" 不可省略：
        stream_mode="messages" 仅在 version="v2" 下生效。
        v1 模式下 messages mode 行为不确定。

    为什么用 dict 风格 chunk["type"] 而非 chunk.type：
        StreamPart 是 TypedDict 子类，官方文档标准写法为 dict 风格。

    为什么 context=graph_context 每次 stream 都传：
        context 不被 checkpointer 持久化（三层配置架构），
        每次 invoke/stream 需独立传入。
    """
    stream_mode = ["messages", "updates"] if debug else "messages"
    full_answer = ""

    print("\n🤖 答：", end="", flush=True)

    try:
        for part in graph.stream(
            input_state,
            config=session.config,
            context=graph_context,
            version="v2",
            stream_mode=stream_mode,
        ):
            if part["type"] == "messages":
                msg, metadata = part["data"]
                if (
                    isinstance(msg, (AIMessage, AIMessageChunk))
                    and msg.content
                    and metadata.get("langgraph_node") in _STREAM_OUTPUT_NODES
                ):
                    print(msg.content, end="", flush=True)
                    full_answer += msg.content
            elif part["type"] == "updates" and debug:
                logger.debug("节点更新", data=part["data"])

    except Exception as stream_err:
        if full_answer:
            print("\n[流式中断，重新获取完整回答...]")
        logger.warning("流式输出失败，回退到同步模式", error=str(stream_err))

        try:
            result = graph.invoke(
                input_state,
                config=session.config,
                context=graph_context,
                version="v2",
            )
            if result.value and result.value.get("messages"):
                ai_msg = result.value["messages"][-1]
                if isinstance(ai_msg, AIMessage):
                    full_answer = ai_msg.content
                    print(full_answer)
        except RAGSystemError:
            raise
        except Exception:
            pass

    if full_answer and not full_answer.endswith("\n"):
        print()

    return full_answer


def _invoke_response(
    graph,
    input_state: dict,
    session: SessionInfo,
    graph_context: GraphContext,
) -> str:
    """非流式输出 — 一次性获取完整回答。

    RAGSystemError 不做静默吞没：抛出让 cli_loop 的 except RAGSystemError
    处理器统一打印错误信息，保持流式/非流式两路径的错误展示一致。
    """
    try:
        result = graph.invoke(
            input_state,
            config=session.config,
            context=graph_context,
            version="v2",
        )
        if result.value and result.value.get("messages"):
            ai_msg = result.value["messages"][-1]
            if isinstance(ai_msg, AIMessage):
                print(f"\n🤖 答：{ai_msg.content}")
                return ai_msg.content
    except RAGSystemError:
        raise
    except Exception:
        pass
    return ""


# ============================================================
# CLI REPL 循环
# ============================================================


def cli_loop(
    graph,
    session: SessionInfo,
    use_stream: bool = True,
    debug: bool = False,
    graph_context: GraphContext | None = None,
) -> None:
    """REPL 主循环：读取用户输入 → 调用 LangGraph 图 → 打印回答。

    为什么每轮只传 HumanMessage 不传完整历史：
        checkpointer 自动从存储中加载历史 messages 并与新传入的合并
        （add_messages reducer）。完整传入会导致消息重复。
    """
    if graph_context is None:
        graph_context = GraphContext()

    print(_WELCOME_MESSAGE)
    logger.info("会话开始", thread_id=session.thread_id)

    try:
        import structlog.contextvars
        structlog.contextvars.bind_contextvars(thread_id=session.thread_id)
    except (ImportError, AttributeError):
        pass

    while True:
        try:
            user_input = input("\n🤔 你：")
            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.lower() in _EXIT_COMMANDS:
                print(_GOODBYE_MESSAGE)
                break

            input_state = {"messages": [HumanMessage(content=user_input)]}

            logger.info("开始处理问题", question=user_input[:50])

            if use_stream:
                full_answer = _stream_response(
                    graph, input_state, session, graph_context, debug,
                )
            else:
                full_answer = _invoke_response(
                    graph, input_state, session, graph_context,
                )

            # 获取来源信息
            try:
                state_values = graph.get_state(session.config).values
                sources = _extract_sources(state_values)
            except Exception as e:
                logger.warning("获取来源失败", error=str(e))
                sources = []

            sources_str = format_sources(sources)
            if sources_str:
                print(sources_str)

            print(_SEPARATOR)

        except KeyboardInterrupt:
            print(f"\n{_GOODBYE_MESSAGE}")
            print(_RESUME_HINT.format(thread_id=session.thread_id))
            break

        except EOFError:
            print(f"\n{_GOODBYE_MESSAGE}")
            break

        except RAGSystemError as e:
            print(f"\n❌ 系统错误：{e}")
            logger.error("RAG 系统异常", error=str(e), error_type=type(e).__name__)
            print(_SEPARATOR)

        except Exception as e:
            print(f"\n❌ 未预期的错误：{e}")
            logger.error("未预期异常", error=str(e), error_type=type(e).__name__)
            print(_SEPARATOR)

    try:
        import structlog.contextvars
        structlog.contextvars.unbind_contextvars("thread_id")
    except (ImportError, AttributeError):
        pass


# ============================================================
# main 入口
# ============================================================


def main() -> None:
    """CLI 入口函数：初始化 → 创建图 → 启动 REPL。"""
    args = parse_args()
    load_dotenv(override=True)

    # Windows GBK 终端补偿：将 stdout/stderr 编码升到 UTF-8，避免 emoji/中文打印崩溃
    if sys.stdout.encoding and sys.stdout.encoding.lower() in ("gbk", "gb2312"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

    setup_logging(level="DEBUG" if args.debug else "INFO", json_format=False)

    thread_id = args.thread_id or uuid.uuid4().hex[:8]
    session = SessionInfo(thread_id)
    graph_context = GraphContext(max_tokens=args.max_tokens)

    logger.info("LangGraph RAG CLI 启动", thread_id=session.thread_id)

    try:
        with create_checkpointer(settings) as checkpointer:
            graph = build_graph(settings, checkpointer=checkpointer)
            cli_loop(
                graph,
                session,
                use_stream=not args.no_stream,
                debug=args.debug,
                graph_context=graph_context,
            )
    except RAGSystemError as e:
        logger.error("初始化失败", error=str(e))
        print(f"❌ 初始化失败：{e}")
        sys.exit(1)
    except Exception as e:
        logger.error("初始化失败", error=str(e))
        print(f"❌ 初始化失败：{e}")
        sys.exit(1)

    logger.info("LangGraph RAG CLI 退出")
