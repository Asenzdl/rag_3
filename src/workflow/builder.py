"""图构建模块 — 组装 LangGraph StateGraph 并编译为可执行图。

本模块定义 build_graph 函数，将路由/检索/生成/问候/降级节点
组装为完整的问答工作流。

核心设计：
1. **模块化组装**：图构建逻辑封装在 build_graph 中，便于测试和不同环境配置
2. **配置驱动**：通过 Settings 注入依赖，与 factories.py 模式一致
3. **前瞻性设计**：图结构为 Task 2.6 的循环和安全阀预留扩展点

图拓扑（Task 2.3）：
    START → route → [retrieve | greeting | fallback]
    retrieve → generate → END
    greeting → END
    fallback → END
"""

import structlog
from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.core.factories import create_llm, create_retriever
from src.core.settings import Settings
from src.workflow.edges import route_after_classification
from src.workflow.nodes import create_workflow_nodes
from src.workflow.state import GraphState

logger = structlog.get_logger(__name__)


# ============================================================
# 预设回复常量
# ============================================================

GREETING_RESPONSE = (
    "你好！我是文档问答助手，可以帮你解答与文档相关的问题。"
    "请问有什么我可以帮助你的？"
)
"""问候预设回复 — 独立于 fallback 回复，两者语义不同：
    greeting = "打招呼，引导用户提问"
    fallback = "无法回答，告知用户限制"
    两者措辞和语气完全不同，不应合并。"""

FALLBACK_RESPONSE = (
    "抱歉，我无法回答这个问题。我的知识范围限于文档库中的内容，"
    "请尝试提出与文档主题相关的问题。"
)
"""降级预设回复 — 明确告知用户系统能力边界。"""


# ============================================================
# 终端节点函数
# ============================================================

def _greeting_node(state: GraphState) -> dict:
    """问候节点：返回预设问候回复。

    为什么是模块级函数而非闭包（功能取舍）：
        greeting 节点无需注入外部依赖（纯预设回复），
        模块级函数最简单。如果后续需要 LLM 生成动态问候，
        可改为闭包注入——但当前无此需求，不超前实现。
    """
    return {"messages": [AIMessage(content=GREETING_RESPONSE)]}


def _fallback_node(state: GraphState) -> dict:
    """降级节点：返回预设降级回复。

    为什么是独立节点而非复用 generate_node 的空检索逻辑（设计决策）：
        generate_node 的空检索回复是"检索结果为空"的提示，
        fallback 的回复是"超出能力范围"的提示——语义不同。
        合并两者会模糊业务边界，且 fallback 节点不经过检索/生成流程，
        响应更快、成本更低（无 LLM 调用）。
    """
    return {"messages": [AIMessage(content=FALLBACK_RESPONSE)]}


# ============================================================
# 图构建函数
# ============================================================

def build_graph(
    settings: Settings,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """构建问答工作流图。

    图拓扑：
        START → route → [retrieve | greeting | fallback]
        retrieve → generate → END
        greeting → END
        fallback → END

    为什么 build_graph 接受 Settings 而非直接接受依赖（设计决策）：
        与 factories.py 的工厂模式一致——Settings 是配置的唯一来源。
        调用方只需传入 settings 即可获取配置好的图，无需了解内部组件。
        测试时通过 mock factories 模块注入 Mock 依赖。

    为什么 checkpointer 是外部传入而非内部创建（设计决策）：
        checkpointer 是资源（数据库连接），其生命周期需要由调用方管理
        （何时打开、何时关闭）。build_graph 只负责"组装图"，
        不负责"管理资源"。测试时传入 None 可在无持久化场景下运行。

    为什么 greeting 和 fallback 是模块级函数而非闭包（功能取舍）：
        这两个节点无需注入外部依赖（纯预设回复），模块级函数更简单。
        如果后续需要 LLM 生成问候回复，可改为闭包注入。

    为什么 generate 后用直接边而非条件边（设计决策）：
        当前图为线性流（无循环），generate 直接到 END 是最简洁的设计。
        Task 2.6 引入循环时，将 generate → END 改为条件边，
        添加 should_continue 路由函数和安全阀节点。

    Args:
        settings: 全局配置实例
        checkpointer: 可选的检查点管理器。传入后支持状态持久化，
            调用 invoke 时需传入 config={"configurable": {"thread_id": "xxx"}}

    Returns:
        编译后的 CompiledStateGraph
    """
    # 第1步：通过 factories 创建依赖
    retriever = create_retriever(settings)
    llm = create_llm(settings.llm_provider, settings)

    # 第2步：通过 create_workflow_nodes 创建节点函数
    #   不再传入 prompt——generate_node 通过 src/workflow/prompts.py 中的
    #   build_generate_messages() 自管理模板，与 generation 路径完全解耦。
    nodes = create_workflow_nodes(
        retriever=retriever,
        llm=llm,
        max_iterations=settings.max_iterations,
    )

    # 第3步：创建 StateGraph
    graph = StateGraph(GraphState)

    # 第4步：添加节点
    # 先添加所有节点，再连接边——LangGraph 要求节点在边引用前已注册
    graph.add_node("route", nodes["route"])
    graph.add_node("retrieve", nodes["retrieve"])
    graph.add_node("generate", nodes["generate"])
    graph.add_node("greeting", _greeting_node)
    graph.add_node("fallback", _fallback_node)

    # 第5步：添加边
    # 入口边：START → route
    graph.add_edge(START, "route")

    # 条件边：route → [retrieve | greeting | fallback]
    graph.add_conditional_edges("route", route_after_classification)

    # 固定边：retrieve → generate
    graph.add_edge("retrieve", "generate")

    # 终止边：generate / greeting / fallback → END
    graph.add_edge("generate", END)
    graph.add_edge("greeting", END)
    graph.add_edge("fallback", END)
    # TODO(Task 2.6): 将 generate → END 改为条件边，
    #   添加 should_continue 路由函数和安全阀节点

    # 第6步：编译并返回
    #   注入：checkpointer（可 Mock，可传 None）
    #   checkpointer=None 时等价于之前的行为（无持久化）
    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("工作流图构建完成", has_checkpointer=checkpointer is not None)

    return compiled


__all__ = [
    "FALLBACK_RESPONSE",
    "GREETING_RESPONSE",
    "build_graph",
]
