# Task 2.1 LangGraph 状态定义 - 架构设计

> **原始需求**：`.project/outline/phase_2_langgraph/task_2.1_state.md`
> **涉及文件**：`src/workflow/state.py`、`tests/test_graph_state.py`

---

## 架构决策与权衡

### 先读：这不是填空题

状态定义看似简单（一个 TypedDict + 几个字段），但字段选择、reducer 策略、类型注解方式，决定了后续所有节点（2.2-2.6）的实现方式——状态是图的"宪法"，一旦定义，所有节点必须遵守。

---

### 入口判定

1. **`documents` 字段的 reducer 策略**：覆盖 vs 替换 vs 不用 reducer。选择覆盖意味着每次检索替换旧文档；选择替换意味着用 Annotated + 自定义 reducer 合并文档列表。两种方案改变 `documents` 字段的语义模型——覆盖语义是"当前轮次的检索结果"，替换语义是"累积的所有检索结果"。**命中**。
2. **`messages` 的 reducer 选择**：使用 `add_messages` vs 手动管理。`add_messages` 是 LangGraph 的惯用 reducer，自动处理增量追加和同 ID 消息的替换。不使用 `add_messages` 则每个节点必须手动管理消息列表的合并。两种方案改变节点返回值的写法。**命中**。
3. **状态字段的粒度**：是否将 `question` 作为独立字段 vs 仅存在于 `messages` 中。独立字段让节点函数签名清晰（`state["question"]` vs 从 `messages[-1]` 提取），但增加冗余。影响节点实现方式和可读性。**命中**。

---

### 决策 1：`documents` 字段的 reducer 策略 — 覆盖 vs 累积

**语境**：本项目的 RAG 流程是"用户提问 → 检索 → 生成"，每次问答是独立的。检索节点返回的文档是针对当前问题的，上一轮的检索结果对当前轮的生成无意义（甚至有害——混入不相关文档会降低回答质量）。Task 2.3 的图结构中，检索节点直接覆盖 `documents`，生成节点读取 `documents` 生成回答。

**候选对比**：

- **方案 A**：`documents: List[Document]`（无 Annotated，无 reducer）— 节点返回 `{"documents": new_list}` 直接覆盖
  - 在本项目语境下的优势：语义直觉——每轮检索结果独立，覆盖是正确行为；节点返回值简单，无需理解 reducer 机制
  - 在本项目语境下的硬伤：与 `messages` 字段的 `Annotated` 风格不一致，读者可能误以为遗漏了 reducer

- **方案 B**：`documents: Annotated[List[Document], add_documents_reducer]`（自定义 reducer 实现覆盖行为）
  - 在本项目语境下的优势：与 `messages` 风格一致，展示 `Annotated` + reducer 的用法
  - 在本项目语境下的硬伤：为了"风格一致"而引入一个 reducer，该 reducer 的行为与不写 reducer 完全相同（覆盖），属于过度设计；且面试中如果被问到"为什么 documents 不用 add_messages"，需要解释"覆盖是刻意设计"，但如果直接不写 reducer，覆盖行为本身就是默认值，无需解释

**反驳推演**：如果选方案 B，面试官问"你的 documents reducer 做了什么"——回答"它覆盖旧值"。面试官追问"覆盖不就是默认行为吗，为什么还要写 reducer？"——无法给出有力理由。自定义 reducer 只在需要非默认行为时才有价值（如合并、去重）。

**结论**：选 A，根本理由是本项目的检索语义是"每轮独立，上轮结果无效"——覆盖是正确行为，且覆盖是 TypedDict 无 reducer 时的默认行为，不需要额外机制。如果 Task 2.6 的自适应路由需要在状态中累积多轮检索结果（如对比前后两轮检索差异），结论会反转——需要自定义 reducer 合并文档列表。

**反事实自检**：

- [x] 方案 B 不再失效（如果多轮检索需要累积文档），两方案都可行 → "每轮检索独立，上轮结果无效"正是让方案 B 失效的原因 → 验证通过

---

### 决策 2：`question` 是否作为独立字段

**语境**：LangGraph 的惯例是通过 `messages[-1].content` 提取用户问题，不单独存 `question` 字段。但本项目的节点（检索节点、生成节点）都需要 `question`，如果每次都从 `messages` 提取，节点内部会多一步解析逻辑，且 `messages[-1]` 的假设（最后一条一定是用户消息）在某些场景下不成立（如 LLM 重试时最后一条可能是 AIMessage）。

**候选对比**：

- **方案 A**：`question: str` 作为独立字段
  - 在本项目语境下的优势：节点函数直接 `state["question"]` 读取，无需解析 messages；字段类型明确（`str`），IDE 提示清晰；语义透明——"当前要回答的问题是什么"一目了然
  - 在本项目语境下的硬伤：与 `messages` 存在数据冗余——同一信息在两个字段中存储；需确保 `question` 和 `messages[-1]` 始终一致

- **方案 B**：不设 `question` 字段，从 `messages` 中提取
  - 在本项目语境下的优势：无冗余，单一数据源（SSOT）；符合 LangGraph 社区惯例
  - 在本项目语境下的硬伤：每个需要 `question` 的节点都要写提取逻辑；提取逻辑隐含假设（"最后一条 HumanMessage 是当前问题"），如果消息列表被中间节点修改（如摘要压缩删除旧消息），假设可能不成立

**反驳推演**：如果选方案 B，Task 2.2 的检索节点需要这样获取问题：`question = [m for m in state["messages"] if isinstance(m, HumanMessage)][-1].content`。这在摘要压缩后可能拿错消息（Task 2.5 的摘要会替换历史消息，但应保留最近一条 HumanMessage——需要额外约束）。而方案 A 中，路由节点将用户问题写入 `question`，后续节点直接读取，无需关心 `messages` 的内部结构。

**结论**：选 A，根本理由是本项目节点（检索/生成/路由）都需要"当前问题"这一明确语义，独立字段消除了从 `messages` 提取的隐含假设和维护负担。如果 LangGraph 的图只包含纯对话场景（无检索/路由），不需要 `question` 字段——但本项目的核心是 RAG 流程，不是纯聊天。

**反事实自检**：

- [x] 方案 B 不再失效（如果所有节点都只处理 messages 而不需要单独的问题引用），两方案都可行 → "节点需要直接引用当前问题"正是让方案 B 失效的原因 → 验证通过

---

### 决策 3：额外状态字段 — `iteration_count` 和 `route_decision` 的必要性

**语境**：`iteration_count` 在验收标准中明确要求，用于 Task 2.3 的条件边限制最大重试次数。`route_decision` 不在验收标准中，但 Task 2.2 的路由节点需要将意图分类结果传递给条件边——如果不存入状态，条件边如何获取路由结果？

**候选对比**：

- **方案 A**：仅定义验收标准要求的字段（`messages`、`documents`、`iteration_count`）
  - 在本项目语境下的优势：严格遵守"禁止超前实现"原则，不为未到来的 Task 预先定义字段
  - 在本项目语境下的硬伤：Task 2.2 的路由节点需要一个地方存放意图分类结果供条件边读取。如果不定义 `route_decision` 字段，路由节点无法通过返回字典更新状态来传递路由结果，必须使用 LangGraph 的"命令模式"（返回 `Command` 对象），增加了节点实现复杂度

- **方案 B**：额外定义 `route_decision: str` 字段
  - 在本项目语境下的优势：路由节点返回 `{"route_decision": "retrieve"}` 即可，条件边直接读 `state["route_decision"]`，实现直觉清晰；与 Task 2.2 的节点设计自然衔接
  - 在本项目语境下的硬伤：超前实现——当前 Task 只要求 `messages`、`documents`、`iteration_count`

**反驳推演**：如果选方案 A，Task 2.2 实现路由节点时必须定义 `route_decision` 字段——这是不可避免的。区别只是"在 2.1 定义"还是"在 2.2 追加"。在 2.2 追加意味着修改 `GraphState` 定义，且 2.2 的设计文档需要解释"为什么在节点实现 Task 中修改了状态定义"——这是职责泄露。状态定义应该在 2.1 中一次性完成，因为状态是图的契约，后续 Task 应基于此契约实现，而非反过来。

**结论**：选 B，根本理由是状态是图的契约文件，应一次性定义所有下游 Task 需要的字段——`route_decision` 不是"超前实现"，而是"2.1 作为状态定义 Task 的职责"。如果下游 Task 出现当前未预见的字段需求，再追加定义——但 `route_decision` 的需求在 2.2 outline 中已明确，不是"未到来"的需求。

**反事实自检**：

- [x] 方案 A 不再失效（如果路由节点使用 Command 模式而非状态字段传递路由结果），两方案都可行 → "路由节点通过状态字段传递路由结果"正是让方案 A 失效的原因 → 验证通过

---

### 质量准则豁免

- **封装与抽象**：部分豁免。TypedDict 是 LangGraph 框架要求的状态定义方式，不支持自定义封装逻辑。字段全部为 `ReadOnly` 或公开访问是框架约束，不是设计缺陷。
- **设计模式**：部分豁免。状态定义本身是数据结构，不涉及设计模式。但 `add_messages` reducer 体现了策略模式的思想（不同的字段使用不同的合并策略）。

---

## 模块结构

### 文件组织
```
src/workflow/
├── __init__.py      # 公共导出 GraphState
└── state.py         # LangGraph 状态定义
```

### 关键外部依赖（仅列非标准库）
```
state.py
├── langgraph.graph     # StateGraph, START, END（仅类型注解引用，不直接使用）
├── langgraph.graph.message  # add_messages reducer
└── langchain_core.messages  # BaseMessage（messages 字段类型）
    └── langchain_core.documents  # Document（documents 字段类型）
```

### 职责边界
```
state.py 职责：
✅ 包含：GraphState TypedDict 定义（所有字段 + 类型注解 + reducer）
✅ 包含：字段级别的 docstring 说明每个字段的语义和使用场景
❌ 不包含：节点函数定义 ← 属于 nodes.py（Task 2.2）
❌ 不包含：图构建逻辑 ← 属于 builder.py（Task 2.3）
❌ 不包含：业务逻辑（如检索、生成、路由）← 属于各节点模块
```

### 与后续 Task 的接口衔接
- Task 2.2：节点函数签名 `def retrieve_node(state: GraphState) -> dict`，读取 `state["question"]`/`state["documents"]`，返回更新的字段
- Task 2.3：`StateGraph(GraphState)` 构造图，`add_conditional_edges` 读取 `state["route_decision"]` 和 `state["iteration_count"]`
- Task 2.4：Checkpointer 自动序列化/反序列化 `GraphState` 的所有字段
- Task 2.5：`messages` 字段的 `add_messages` reducer 支持摘要压缩后的消息替换
- Task 2.6：条件边读取 `route_decision` 做自适应路由

---

## 错误处理策略

本 Task 仅定义数据结构，不涉及异常处理。后续 Task 在节点实现时定义异常策略。

---

## 测试策略概要

### 可独立测试的函数/方法
- `add_messages` reducer 行为：纯函数，可直接调用验证
- `GraphState` 字段完整性：通过构造状态字典验证字段可赋值、类型正确

### 必须覆盖的关键测试场景
- `add_messages` 连续追加：两个节点分别返回消息，状态中 `messages` 应包含两者合并结果
- `add_messages` 同 ID 替换：返回与已有消息相同 ID 的消息时，应替换而非追加
- `add_messages` 混合操作：同时包含新消息和替换消息
- `documents` 覆盖行为：第二个节点返回 `documents` 后，状态中应只有新文档
- `iteration_count` 自增行为：节点返回 `iteration_count` 后，状态中应为新值
- `route_decision` 更新行为：节点返回 `route_decision` 后，状态中应为新值

### Mock 边界
- 无需 Mock——`add_messages` 是 LangGraph 提供的纯函数，可直接调用

---

## 代码蓝图：施工图纸级别

### state.py

```python
"""LangGraph 工作流状态定义 — 所有节点间数据传递的唯一载体。

为什么用 TypedDict 而非 Pydantic BaseModel（设计决策）：
    LangGraph 的 StateGraph 要求状态类型为 TypedDict 子类。
    TypedDict 是 Python 标准库的类型提示工具，运行时零开销（仅类型检查时使用）。
    Pydantic BaseModel 会引入运行时校验开销，且与 LangGraph 的
    状态更新机制（节点返回 dict 合并到状态）不兼容。

为什么用 Annotated + reducer（面试知识点）：
    Annotated[list[BaseMessage], add_messages] 告诉 LangGraph：
    当节点返回 {"messages": [new_msg]} 时，不是覆盖整个 list，
    而是调用 add_messages(state["messages"], [new_msg]) 将新消息追加。
    没有 Annotated 的字段（如 documents），节点返回值直接覆盖。
    这就是 reducer 的核心作用——定义"状态合并策略"。

StateGraph vs MessageGraph（面试知识点）：
    MessageGraph 是 StateGraph 的特化版本，状态仅包含 messages 字段。
    自定义 StateGraph 可扩展更多字段（如 documents、iteration_count），
    本项目需要自定义字段，因此使用 StateGraph。
"""
```

```python
class GraphState(TypedDict):
    """LangGraph 工作流全局状态 — 节点间数据传递的唯一载体。

    设计原则：
        1. 字段精简：只存储跨节点需要传递的数据，临时变量在节点内部处理
        2. 类型完整：所有字段有明确类型注解，便于 IDE 提示和静态检查
        3. Reducer 选择：messages 用 add_messages（增量追加），
           其他字段无 reducer（直接覆盖）

    状态字段与节点交互模式：
        - 路由节点：读取 messages → 写入 route_decision
        - 检索节点：读取 question → 写入 documents
        - 生成节点：读取 documents + question + messages → 写入 messages + iteration_count
        - 安全阀节点：读取 iteration_count → 写入 messages（预设回复）
    """
```

```python
    messages: Annotated[list[BaseMessage], add_messages]
    """对话消息列表 — 增量追加而非覆盖。

    为什么用 add_messages reducer（面试知识点）：
        1. 每个节点返回的消息被追加到现有列表，而非替换
        2. add_messages 还处理同 ID 消息的替换（如修改已有消息）
        3. 不使用 reducer 时，节点返回 {"messages": [...]} 会覆盖整个列表，
           之前的对话历史全部丢失

    消息类型说明：
        - HumanMessage：用户输入（由 CLI/API 层构造后注入初始状态）
        - AIMessage：LLM 生成结果（由生成节点追加）
        - SystemMessage：系统指令（如 Prompt 前缀，可在图初始化时注入）
    """
```

```python
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
```

```python
    documents: list[Document]
    """当前轮次的检索结果 — 直接覆盖而非累积。

    为什么不用 reducer（设计决策）：
        本项目每轮问答独立——新的检索结果与上一轮无关，
        覆盖是正确语义。如果使用累积 reducer，
        多轮检索结果混合会降低生成质量。

    与 messages 的对比：
        messages 用 add_messages 因为对话历史需要累积；
        documents 直接覆盖因为检索结果是每轮独立替换。
        两者的 reducer 策略差异反映了业务语义差异。
    """
```

```python
    iteration_count: int
    """迭代计数器 — 防止工作流无限循环。

    递增策略：
        每次进入生成节点时 +1，条件边检查是否超过阈值。
        Task 2.3 的安全阀机制：iteration_count > max_iterations → 强制结束。

    为什么从 0 开始：
        0 表示尚未进入生成节点，便于条件边判断"是否首次进入"。
        初始状态设为 0。
    """
```

```python
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
```

---

## 常见坑点

1. **`add_messages` 不是 `extend`**：`add_messages` 的行为比简单的 `list.extend` 更复杂——它处理同 ID 消息的替换（LangGraph 的消息有唯一 ID，相同 ID 的消息会被替换而非追加）。测试时如果不指定消息 ID，每条消息自动生成唯一 ID，行为等同于 `extend`；但如果手动指定相同 ID，行为是替换。

2. **TypedDict 的运行时行为**：`TypedDict` 是纯类型提示工具，运行时不做任何校验。构造 `GraphState` 时传入错误类型的值不会报错，但在节点函数中访问时会得到不符合预期的类型。因此类型注解的准确性至关重要——它是对开发者的契约，不是对运行时的约束。

3. **`documents` 初始值问题**：TypedDict 没有默认值机制。创建初始状态时必须包含所有字段，否则类型检查器会报错。`documents` 的初始值应为 `[]`（空列表），`iteration_count` 应为 `0`，`route_decision` 应为 `""`。

4. **`list[BaseMessage]` vs `List[BaseMessage]`**：Python 3.9+ 支持内置 `list[X]` 泛型语法（PEP 585），无需从 `typing` 导入 `List`。本项目使用 Python 3.12+，应使用 `list[X]` 而非 `List[X]`。但 `Annotated` 仍需从 `typing` 导入（Python 3.12 之前）或从 `typing_extensions` 导入。

5. **状态字段精简原则的边界**：不要因为"将来可能用到"就添加字段。每多一个字段，检查点序列化开销增加、节点需要理解更多字段语义。`route_decision` 被纳入是因为 Task 2.2 的 outline 明确需要，而非凭预判添加。
