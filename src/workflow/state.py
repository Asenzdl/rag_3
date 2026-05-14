"""LangGraph 工作流状态定义 — 所有节点间数据传递的唯一载体。

本模块定义 GraphState TypedDict，作为 LangGraph StateGraph 的状态类型。
状态是图的"宪法"——所有节点的输入和输出都以此为契约。

核心设计：
1. **TypedDict + Annotated 组合**（面试知识点）：
   TypedDict 定义字段类型，Annotated 配合 reducer 定义合并策略。
   LangGraph 在节点返回状态更新时，根据 Annotated 中指定的 reducer
   决定如何合并新旧值；未标注 reducer 的字段直接覆盖。

2. **add_messages reducer**（面试知识点）：
   messages 字段使用 add_messages，实现消息列表的增量追加而非覆盖。
   add_messages 还处理同 ID 消息的替换——当返回的消息与已有消息
   具有相同 ID 时，替换旧消息而非追加（LangGraph 的消息有唯一 ID）。

3. **StateGraph vs MessageGraph**（面试知识点）：
   MessageGraph 是 StateGraph 的特化版本，状态仅包含 messages 字段。
   自定义 StateGraph 可扩展更多字段（如 documents、iteration_count），
   本项目需要自定义字段，因此使用 StateGraph。

4. **字段精简原则**（生产级注意事项）：
   状态中只存储跨节点需要传递的数据，临时变量在节点内部处理。
   字段过多会增加序列化开销和检查点存储成本。

为什么用 TypedDict 而非 Pydantic BaseModel：
    LangGraph 的 StateGraph 要求状态类型为 TypedDict 子类。
    TypedDict 运行时零开销（仅类型检查时使用），而 Pydantic BaseModel
    会引入运行时校验开销，且与 LangGraph 的状态更新机制
    （节点返回 dict 合并到状态）不兼容。

使用示例：
    from src.workflow.state import GraphState

    # 初始状态
    initial_state: GraphState = {
        "messages": [HumanMessage(content="LangGraph 是什么？")],
        "question": "",
        "documents": [],
        "iteration_count": 0,
        "route_decision": "",
    }

    # 节点函数签名
    def retrieve_node(state: GraphState) -> dict:
        docs = retriever.invoke(state["question"])
        return {"documents": docs}  # 直接覆盖 documents
"""

from dataclasses import dataclass
from typing import Annotated

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing import TypedDict


class GraphState(TypedDict):
    """LangGraph 工作流全局状态 — 节点间数据传递的唯一载体。

    设计原则：
        1. 字段精简：只存储跨节点需要传递的数据，临时变量在节点内部处理
        2. 类型完整：所有字段有明确类型注解，便于 IDE 提示和静态检查
        3. Reducer 选择：messages 用 add_messages（增量追加），
           其他字段无 reducer（直接覆盖）

    状态字段与节点交互模式（Task 2.2 实现）：
        - 路由节点：读取 messages → 写入 route_decision + question
        - 检索节点：读取 question → 写入 documents
        - 生成节点：读取 documents + question + messages → 写入 messages + iteration_count
        - 安全阀节点：读取 iteration_count → 写入 messages（预设回复）

    Reducer 策略差异反映业务语义差异：
        messages 用 add_messages（增量追加）因为对话历史需要累积；
        documents 直接覆盖因为检索结果是每轮独立替换。
    """

    messages: Annotated[list[BaseMessage], add_messages]
    """对话消息列表 — 增量追加而非覆盖。

    为什么用 add_messages reducer：
        1. 每个节点返回的消息被追加到现有列表，而非替换
        2. add_messages 还处理同 ID 消息的替换（如修改已有消息）
        3. 不使用 reducer 时，节点返回 {"messages": [...]} 会覆盖整个列表，
           之前的对话历史全部丢失

    消息类型说明：
        - HumanMessage：用户输入（由 CLI/API 层构造后注入初始状态）
        - AIMessage：LLM 生成结果（由生成节点追加）
        - SystemMessage：系统指令（如 Prompt 前缀，可在图初始化时注入）
    """

    question: str
    """当前用户问题 — 由路由节点从 messages 中提取并写入。

    为什么是独立字段而非从 messages 推导（设计决策）：
        1. 消除隐含假设：直接 state["question"] 读取 vs
           从 messages[-1] 提取（假设最后一条是 HumanMessage）
        2. 摘要压缩安全：Task 2.5 的摘要可能修改 messages 列表，
           独立字段不受影响
        3. 类型明确：str vs BaseMessage.content（需类型转换）

    生命周期：
        路由节点负责从 messages 中提取最新用户消息，
        写入 question 字段供后续节点使用。
    """

    documents: list[Document]
    """当前轮次的检索结果 — 直接覆盖而非累积。

    为什么不用 reducer（设计决策）：
        本项目每轮问答独立——新的检索结果与上一轮无关，
        覆盖是正确语义。如果使用累积 reducer，
        多轮检索结果混合会降低生成质量。
    """

    iteration_count: int
    """迭代计数器 — 防止工作流无限循环。

    递增策略：
        每次进入生成节点时 +1，条件边检查是否超过阈值。
        Task 2.3 的安全阀机制：iteration_count > max_iterations → 强制结束。

    为什么从 0 开始：
        0 表示尚未进入生成节点，便于条件边判断"是否首次进入"。
    """

    route_decision: str
    """路由决策结果 — 条件边根据此字段决定下一跳。

    可能的值（由 Task 2.2 的路由节点决定）：
        - "retrieve"：知识库问题，进入检索流程
        - "fallback"：无法回答的问题，进入降级处理
        - "greeting"：问候类，直接回复

    为什么是 str 而非 Enum（功能取舍）：
        LangGraph 的 add_conditional_edges 路由函数返回 str 标签，
        使用 str 与框架 API 直接对齐，无需额外的 .value 转换。
        若后续需要强约束（如拼写错误防护），可升级为 Literal 类型。
    """

    summary: str
    """对话摘要文本 — Task 2.5 对话记忆管理使用。

    为什么是独立字段而非在 messages 列表中存储摘要消息（设计决策）：
        1. 路由节点反向遍历 messages 找最后一条 HumanMessage 时，
           不受摘要消息干扰
        2. 增量扩展自然：state["summary"] 为空 = 创建，非空 = 扩展
        3. 摘要不占用 messages 的 token 配额（不参与 memory 触发门槛计算）
        4. 与 LangGraph 官档的 summarize_conversation 模式一致

    生命周期：
        - 初始值：""（空字符串，表示无摘要）
        - memory_node 摘要成功后写入新值
        - trim 降级不修改此字段（裁剪不生成摘要）
        - build_generate_messages 读取此值注入到 SystemMessage
    """


@dataclass
class GraphContext:
    """LangGraph 运行时配置 — 每次 invoke 独立传入，不入检查点。

    字段说明：
        max_iterations: 工作流最大迭代次数（安全阀阈值，Task 2.6 条件边使用）
        max_tokens: memory 节点触发阈值。当 messages 列表的估计 token 数
                    超过此值时触发摘要，失败则降级为裁剪。
                    Task 2.5 验收约束要求此字段放在 context_schema 中。
    """
    max_iterations: int = 3
    max_tokens: int = 4000


__all__ = [
    "GraphState",
    "GraphContext",
]
