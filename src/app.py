"""CLI 交互入口：REPL 问答 + 会话状态管理。

本模块是 Phase 1 RAG 系统的用户交互层，提供命令行问答界面。

核心设计：
1. **REPL 模式**：while True + input() 的经典 Read-Eval-Print Loop，
   每轮读取用户问题 → 调用 RAGChain → 打印回答。

2. **流式输出**：默认使用 RAGChain.stream() 逐 token 输出，
   实现打字效果，提升用户体验。

3. **会话状态**：ChatSession 类封装对话历史（List[BaseMessage]），
   为 Task 2.5 对话记忆预留数据结构。

4. **优雅退出**：捕获 KeyboardInterrupt / EOFError，打印告别信息后退出。

5. **容错**：业务异常（RAGSystemError）不中断 REPL，未知异常兜底继续。

使用方式：
    # 直接运行
    python run.py

    # 编程调用
    from run import main
    main()
"""

import sys
from typing import List

import structlog
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.core.config import settings
from src.core.exceptions import RAGSystemError
from src.core.factories import create_rag_chain
from src.generation.citation_chain import ValidatedCitation
from src.generation.rag_chain import RAGChain
from src.utils.logger import bind_request_id, setup_logging, unbind_request_id

logger = structlog.get_logger(__name__)


# ============================================================
# ChatSession 类
# ============================================================


class ChatSession:
    """CLI 会话状态管理器。

    设计意图：
        将"对话历史收集"与"CLI 交互循环"解耦，使会话状态可独立测试，
        且为 Task 2.5 LangGraph 对话记忆预留数据结构兼容性。

    为什么用 List[BaseMessage] 而非 List[str]：
        LangChain 的 Prompt 模板 chat_history 占位符期望
        List[BaseMessage] 类型，直接使用此类型避免后续转换。

    Args:
        max_turns: 最大保留的对话轮数（默认 10）。
            超过时自动丢弃最早的一轮（1 HumanMessage + 1 AIMessage）。
            为什么需要限制：长对话的 history 会导致 Prompt token 爆炸，
            限制轮数是简单有效的截断策略。

    Attributes:
        turn_count: 当前对话轮数
    """

    def __init__(self, max_turns: int = 10):
        """初始化会话。

        步骤：
            # 步骤 1：创建空历史列表 self._history: List[BaseMessage] = []
            # 步骤 2：设置 self._max_turns = max_turns
            # 步骤 3：设置 self.turn_count = 0
        """
        self._history: List[BaseMessage] = []
        self._max_turns = max_turns
        self.turn_count: int = 0

    def add_user_message(self, content: str) -> None:
        """将用户消息添加到历史。

        步骤：
            # 步骤 1：创建 HumanMessage(content=content) 并 append 到 self._history
            # 步骤 2：self.turn_count += 1
            # 步骤 3：调用 self._trim_if_needed() 检查是否超出最大轮数
        """
        self._history.append(HumanMessage(content=content))
        self.turn_count += 1
        self._trim_if_needed()

    def add_ai_message(self, content: str) -> None:
        """将 AI 回复添加到历史。

        步骤：
            # 步骤 1：创建 AIMessage(content=content) 并 append 到 self._history
            # 注意：不加 turn_count，一轮 = 1 HumanMessage + 1 AIMessage
        """
        self._history.append(AIMessage(content=content))

    def get_history(self) -> List[BaseMessage]:
        """返回当前对话历史的只读副本。

        步骤：
            # 返回 list(self._history)（浅拷贝，防止外部修改内部状态）
        """
        return list(self._history)

    def clear(self) -> None:
        """清空对话历史，重置 turn_count。

        步骤：
            # 步骤 1：self._history.clear()
            # 步骤 2：self.turn_count = 0
        """
        self._history.clear()
        self.turn_count = 0

    def _trim_if_needed(self) -> None:
        """当 history 条目数 > max_turns * 2 时，移除最早一轮。

        为什么是 max_turns * 2：一轮包含 2 条消息（Human + AI），
            所以 history 的最大条目数 = max_turns * 2。

        步骤：
            # 步骤 1：计算 max_messages = self._max_turns * 2
            # 步骤 2：若 len(self._history) > max_messages →
            #   移除 self._history 的前 2 个元素（最早的一轮对话）
            #   为什么一次移除 2 个：保持 Human/AI 消息成对，避免孤立的 AIMessage
            # 步骤 3：记录 debug 日志（当前 history 长度、被移除的轮数）
        """
        max_messages = self._max_turns * 2
        if len(self._history) > max_messages:
            # 移除最早的一轮（2 条消息：HumanMessage + AIMessage）
            removed = self._history[:2]
            del self._history[:2]
            logger.debug(
                "对话历史自动裁剪",
                removed_count=len(removed),
                current_history_len=len(self._history),
                max_turns=self._max_turns,
            )


# ============================================================
# 格式化辅助函数
# ============================================================


def format_sources(sources: List[str]) -> str:
    """将来源 URL 列表格式化为可读字符串。

    为什么单独抽取为函数：
        格式化逻辑可能变化（如添加编号、去重、截断过长 URL），
        独立函数便于修改和测试。

    Args:
        sources: 来源 URL 列表（可能有重复）

    Returns:
        格式化后的字符串，如：
        "📚 来源：\n  [1] https://...\n  [2] https://..."
        空列表返回空字符串。
    """
    # 步骤 1：若 sources 为空 → 返回 ""
    if not sources:
        return ""

    # 步骤 2：去重 — 用 dict.fromkeys(sources) 保持顺序去重
    # 为什么用 dict.fromkeys 而非 set：set 不保持顺序，用户期望按检索排名展示
    unique_sources = list(dict.fromkeys(sources))

    # 步骤 3：用 enumerate 从 1 开始编号，每行格式 "  [N] URL"
    # 步骤 4：拼接为 "📚 来源：\n" + 编号列表
    lines = [f"  [{i}] {url}" for i, url in enumerate(unique_sources, 1)]
    return "📚 来源：\n" + "\n".join(lines)


def format_citations(citations: List[ValidatedCitation]) -> str:
    """将引用验证结果格式化为可读字符串。

    Args:
        citations: 引用验证结果列表

    Returns:
        格式化后的字符串，如：
        "✅ 引用验证：\n  [1] ✅ https://...\n  [2] ❌ https://..."
        空列表返回空字符串。
    """
    # 步骤 1：若 citations 为空 → 返回 ""
    if not citations:
        return ""

    # 步骤 2：遍历 citations，每条格式 "  [N] ✅/❌ URL"
    # is_valid=True → ✅，is_valid=False → ❌
    lines = []
    for c in citations:
        icon = "✅" if c.is_valid else "❌"
        lines.append(f"  [{c.number}] {icon} {c.url}")

    # 步骤 3：拼接为 "✅ 引用验证：\n" + 验证列表
    return "✅ 引用验证：\n" + "\n".join(lines)


# ============================================================
# CLI REPL 循环
# ============================================================

# 退出命令集合（不区分大小写）
_EXIT_COMMANDS = {"exit", "quit"}

# 欢迎信息模板
_WELCOME_MESSAGE = """========================================
🤖 RAG 问答系统 v1.0（Phase 1 基础版）
输入问题开始对话，输入 exit/quit 退出
========================================"""

# 告别信息
_GOODBYE_MESSAGE = "👋 感谢使用，再见！"

# 分隔线
_SEPARATOR = "—" * 40


def cli_loop(chain: RAGChain, session: ChatSession) -> None:
    """REPL 主循环：读取用户输入 → 调用 RAGChain → 打印回答。

    设计意图：
        将 REPL 循环逻辑与 main() 的初始化逻辑分离，
        使 cli_loop 可接收 Mock 的 chain 进行测试。

    为什么不在 cli_loop 中创建 RAGChain：
        依赖倒置 — cli_loop 依赖 RAGChain 接口而非具体创建过程，
        便于测试时注入 Mock 对象。

    Args:
        chain: 已初始化的 RAGChain 实例
        session: 会话状态管理器

    退出条件：
        - 用户输入 "exit" / "quit"（不区分大小写）
        - KeyboardInterrupt（Ctrl+C）
        - EOFError（Ctrl+D / Ctrl+Z+Enter）
    """
    # 步骤 1：打印欢迎信息（包含退出提示和当前配置摘要）
    print(_WELCOME_MESSAGE)

    # 步骤 2：进入 while True 循环
    while True:
        try:
            # 步骤 2a：使用 input("🤔 你：") 读取用户输入
            user_input = input("\n🤔 你：")

            # 步骤 2b：strip 输入，若为空字符串 → continue（忽略空行）
            user_input = user_input.strip()
            if not user_input:
                continue

            # 步骤 2c：若输入.lower() in ("exit", "quit") → 打印告别信息 → break
            if user_input.lower() in _EXIT_COMMANDS:
                print(_GOODBYE_MESSAGE)
                break

            # 步骤 2d：session.add_user_message(user_input)
            session.add_user_message(user_input)

            # 步骤 2e：bind_request_id() — 为本轮问答绑定追踪 ID
            request_id = bind_request_id()
            logger.info(
                "开始处理问题",
                question=user_input[:50],
                turn_count=session.turn_count,
                request_id=request_id,
            )

            # 步骤 2f：调用 chain.stream(user_input) 流式输出
            # 累积完整回答到 full_answer 变量
            # 每个 chunk 用 print(chunk, end="", flush=True) 输出
            full_answer = ""
            print("\n🤖 答：", end="", flush=True)
            try:
                for chunk in chain.stream(user_input):
                    print(chunk, end="", flush=True)
                    full_answer += chunk
            except RAGSystemError:
                # RAGSystemError 向上传播，由外层统一处理
                # 为什么不在这里处理：保持异常处理路径一致，
                # 所有 RAGSystemError 都在外层打印统一的 "❌ 系统错误" 消息
                raise
            except Exception as stream_err:
                # 非系统异常（如网络抖动），回退到同步 invoke
                logger.warning(
                    "流式输出失败，回退到同步模式",
                    error=str(stream_err),
                )
                try:
                    result = chain.invoke(user_input)
                    full_answer = result.answer
                    print(full_answer)
                except RAGSystemError:
                    # 同步模式也抛出 RAGSystemError，向上传播
                    raise
                except Exception:
                    # 同步也失败，full_answer 保持为空
                    full_answer = ""

            # 流式输出后 print() 补换行
            # 为什么：stream() 最后一个 chunk 不含换行符，
            #   后续输出（来源信息）会紧跟在回答文本后面
            if full_answer and not full_answer.endswith("\n"):
                print()

            # 步骤 2g：流式输出完成后，获取 sources
            # 通过 chain.retrieve(user_input) 获取 docs
            # 从 docs 提取 sources
            # 注意：retrieve 会触发二次检索，但这是最简实现
            # TODO(Task 2.2): LangGraph 节点将 sources 写入状态，避免二次检索
            sources: List[str] = []
            try:
                docs = chain.retrieve(user_input)
                sources = [doc.metadata.get("source", "") for doc in docs]
            except Exception as e:
                logger.warning(
                    "获取来源失败",
                    error=str(e),
                )

            # 步骤 2h：调用 chain.extract_citations(full_answer, sources) 获取引用
            citations: List[ValidatedCitation] = []
            if full_answer and sources:
                try:
                    citations = chain.extract_citations(full_answer, sources)
                except Exception as e:
                    logger.warning(
                        "引用提取失败",
                        error=str(e),
                    )

            # 步骤 2i：打印 format_sources(sources)
            sources_str = format_sources(sources)
            if sources_str:
                print(sources_str)

            # 步骤 2j：打印 format_citations(citations)
            citations_str = format_citations(citations)
            if citations_str:
                print(citations_str)

            # 步骤 2k：session.add_ai_message(full_answer)
            if full_answer:
                session.add_ai_message(full_answer)

            # 步骤 2l：unbind_request_id() — 清除请求上下文
            unbind_request_id()

            # 步骤 2m：打印分隔线
            print(_SEPARATOR)

        except KeyboardInterrupt:
            # 步骤 3：优雅退出 — 打印告别信息 → break
            # 为什么捕获 KeyboardInterrupt：Ctrl+C 是用户最常见的退出方式
            # 为什么不 re-raise：用户主动中断不应产生 traceback
            print(f"\n{_GOODBYE_MESSAGE}")
            break

        except EOFError:
            # 步骤 4：优雅退出 — 打印告别信息 → break
            # 为什么单独处理 EOFError：Windows 下 Ctrl+Z+Enter 触发 EOFError
            #   而非 KeyboardInterrupt
            print(f"\n{_GOODBYE_MESSAGE}")
            break

        except RAGSystemError as e:
            # 步骤 5：业务异常统一处理
            # 打印用户友好的错误提示
            # 不 break — 系统异常后继续等待下一个问题
            # 为什么不退出：一次 LLM 调用失败不应终止整个会话
            print(f"\n❌ 系统错误：{e}")
            logger.error(
                "RAG 系统异常",
                error=str(e),
                error_type=type(e).__name__,
            )
            unbind_request_id()
            print(_SEPARATOR)

        except Exception as e:
            # 步骤 6：未知异常兜底
            # 不 break — 继续等待下一个问题（容错）
            print(f"\n❌ 未预期的错误：{e}")
            logger.error(
                "未预期异常",
                error=str(e),
                error_type=type(e).__name__,
            )
            unbind_request_id()
            print(_SEPARATOR)


# ============================================================
# main 入口
# ============================================================


def main() -> None:
    """CLI 入口函数：初始化 → 创建链 → 启动 REPL。

    初始化顺序（为什么这样排序）：
        1. load_dotenv() — 确保 API Key 可用（config.py 导入时需要）
        2. setup_logging() — 配置日志（后续所有操作都有日志）
        3. create_rag_chain(settings) — 通过工厂函数创建链（配置驱动）
        4. cli_loop() — 启动 REPL（依赖 chain 实例）

    Raises:
        SystemExit: 初始化失败时（如向量库不存在）以非零状态码退出
    """
    # 步骤 1：load_dotenv(override=True) — 确保环境变量加载
    # 为什么在 main 中再次调用：config.py 模块级调用只执行一次，
    # 但 app.py 作为入口需显式确保环境变量就绪
    load_dotenv(override=True)

    # 步骤 2：setup_logging(level="INFO", json_format=False)
    # 为什么 json_format=False：CLI 开发环境使用控制台渲染器（带颜色、可读性好）
    # TODO(Task 5.5): 日志级别和格式可从配置文件读取
    setup_logging(level="INFO", json_format=False)

    # 步骤 3：记录启动日志
    logger.info("RAG CLI 启动")

    # 步骤 4：创建 RAGChain（通过工厂函数，配置驱动）
    try:
        chain = create_rag_chain(settings)
    except RAGSystemError as e:
        logger.error("RAGChain 初始化失败", error=str(e))
        print(f"❌ 初始化失败：{e}")
        sys.exit(1)
    except Exception as e:
        logger.error("未预期的初始化错误", error=str(e))
        print(f"❌ 初始化失败：{e}")
        sys.exit(1)

    # 步骤 5：创建 ChatSession
    session = ChatSession(max_turns=10)

    # 步骤 6：启动 REPL 循环
    cli_loop(chain, session)

    # 步骤 7：记录退出日志
    logger.info("RAG CLI 退出")


# ============================================================
# 标准入口守卫
# ============================================================

# if __name__ == "__main__":
#     main()