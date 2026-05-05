# Task 2.3 条件边与图构建 - 架构设计

> **原始需求**：`.project/outline/phase_2_langgraph/task_2.3_builder.md`
> **涉及文件**：`src/workflow/builder.py`、`src/workflow/edges.py`、`src/workflow/__init__.py`、`src/core/settings.py`（新增 `max_iterations` 字段）、`tests/test_workflow_builder.py`

---

## 架构决策与权衡

### 先读：图构建不是拼积木

将节点连接成图看似简单（`add_node` → `add_edge` → `compile`），但 **路由函数的职责归属**决定了 edges.py 的模块边界，**build_graph 的签名设计**决定了测试时能否绕过工厂创建真实依赖，**安全阀节点的引入时机**决定了图拓扑是线性还是循环——选错任何一项，后续 Task 都需要重写图结构。

---

### 入口判定

1. **edges.py 职责边界**：edges.py 应只包含条件边路由函数（纯函数 `state -> str`），还是也包含简单终端节点（greeting/fallback）？换方案会改变模块间的依赖方向和 builder.py 的组装逻辑。**命中**。

2. **build_graph 函数签名与依赖创建**：build_graph 接受 `Settings` 并内部创建依赖（与 factories.py 模式一致），还是接受预创建的依赖（便于测试注入）？换方案会改变调用方（app.py、测试）的使用方式和图的可测试性。**命中**。

3. **安全阀节点引入时机**：当前图为线性流（route → retrieve → generate → END），没有循环。但生产级注意事项要求"添加安全阀节点"，面试知识点要求覆盖"循环与递归限制"。在 Task 2.3 添加安全阀 vs 延迟到 Task 2.6（引入循环时一并添加）？换方案会改变 generate 节点后的边类型（直接边 vs 条件边）和图拓扑。**命中**。

4. **greeting 节点的独立设计**：routing.py 定义了三个路由标签（RETRIEVE/GREETING/FALLBACK），但验收标准只提到"route → retrieve 或 fallback"。GREETING 应路由到独立的 greeting 节点还是复用 fallback 节点？换方案会改变条件边路由函数的返回值和终端节点数量。**命中**。

---

### 决策 1：edges.py 职责边界 — 只包含路由函数

**语境**：Task outline 列出 `edges.py` 为新文件，但没有明确其内容范围。条件边路由函数（决定"去哪里"）和简单终端节点（决定"做什么"）在概念上不同——前者是路径选择逻辑，后者是业务执行逻辑。

**候选对比**：

- **方案 A**：edges.py 只包含路由函数（`route_after_classification`）
  - 优势：职责单一——edges.py = "路径选择"；模块名 "edges" 与内容语义对齐
  - 硬伤：greeting/fallback 节点需要在别处定义

- **方案 B**：edges.py 包含路由函数 + 简单终端节点（greeting_node, fallback_node）
  - 优势：所有"边相关"逻辑集中管理
  - 硬伤：混淆了"路由"和"执行"两个不同概念；edges.py 既是路由模块又是节点模块，违反模块分离原则

**反驳推演**：如果选方案 B，edges.py 同时包含"决定去哪"和"到了之后做什么"，后续新增节点（如 Task 2.6 的 safety_valve）时，edges.py 会膨胀为路由+节点的混合模块。方案 A 让 edges.py 保持轻量——只有纯函数，可独立测试，新增路由分支只需修改路由函数。

**结论**：选 A。edges.py 只包含条件边路由函数。greeting/fallback 节点定义在 builder.py 中——它们是图结构的一部分（终端节点），且无需注入外部依赖（纯预设回复），在图组装模块中定义是合理的归属。

**反事实自检**：

- [x] 方案 B 不再失效（如果终端节点需要复杂的依赖注入或业务逻辑），两方案都可行 → "greeting/fallback 是纯预设回复节点，无需注入依赖"正是让方案 B 的混合优势消失的原因 → 验证通过

---

### 决策 2：build_graph 函数签名 — Settings 驱动创建

**语境**：build_graph 需要创建检索器、LLM、Prompt 等依赖，然后调用 create_workflow_nodes 获取节点函数，最后组装图。调用方有两种场景：生产环境需要配置驱动创建（传入 Settings 即可），测试环境需要依赖注入（传入 Mock 对象）。

**候选对比**：

- **方案 A**：`build_graph(settings: Settings) -> CompiledStateGraph`
  - 优势：与 factories.py 的工厂模式一致；调用方只需传入 settings；配置是唯一来源
  - 硬伤：测试需要 mock factories 模块来注入 Mock 依赖

- **方案 B**：`build_graph(retriever, llm, prompt, ...) -> CompiledStateGraph`
  - 优势：依赖显式注入，测试友好
  - 硬伤：调用方需要自己创建所有依赖；与 Settings 配置管理不一致；签名参数多（5+个）

- **方案 C**：混合签名 `build_graph(settings=None, *, retriever=None, llm=None, ...)`
  - 优势：两种场景都支持
  - 硬伤：签名复杂，两种路径需分别测试；增加了 API 表面积和维护负担

**反驳推演**：如果选方案 B，app.py 中需要重复 factories.py 的创建逻辑（create_retriever + create_llm + get_prompt），违反 DRY。方案 A 的"测试需 mock factories"是 Python 测试的标准模式（`unittest.mock.patch`），不是真正的硬伤——mock 工厂函数比手动创建所有依赖更简洁。

**结论**：选 A。与 factories.py 模式一致，Settings 是配置的唯一来源。测试时通过 mock factories 模块注入 Mock 依赖。

**反事实自检**：

- [x] 方案 B 不再失效（如果 build_graph 需要在同一进程中创建多个不同配置的图），两方案都可行 → "当前项目只需一个图实例（单进程服务）"正是让方案 B 的注入优势不突出的原因 → 验证通过

---

### 决策 3：安全阀节点引入时机 — 延迟到 Task 2.6

**语境**：生产级注意事项要求"添加安全阀节点"，面试知识点要求覆盖"循环与递归限制"。但当前图为线性流（route → retrieve → generate → END），没有循环。安全阀只在循环中才有意义——当 generate 后需要回到 retrieve 重试时，iteration_count 超过阈值才触发安全阀。

**候选对比**：

- **方案 A**：Task 2.3 添加安全阀节点 + generate 后条件边
  - 优势：面试知识点有代码载体；为 Task 2.6 预留
  - 硬伤：当前线性流中安全阀永远不会触发；条件边函数总是返回 END，等价于直接边——增加了代码复杂度但无功能差异

- **方案 B**：Task 2.3 不添加安全阀节点，generate 后用直接边 → END；设计文档覆盖面试知识点
  - 优势：图结构简洁，不过度设计；遵循"禁止超前实现"
  - 硬伤：面试知识点仅停留在文档层面，没有代码体现

**反驳推演**：如果选方案 A，需要额外定义：(1) safety_valve 节点函数、(2) should_continue 条件边路由函数、(3) 将 generate → END 改为 generate → should_continue → [END | safety_valve]。但 should_continue 在 Task 2.3 中总是返回 END，safety_valve 节点永远不会执行——这是死代码。死代码比没有代码更糟糕，因为它给读者错误的印象（以为图有循环），且需要维护永远不会执行的路径。

**结论**：选 B。Task 2.3 使用直接边 generate → END。面试知识点在设计文档中覆盖（recursion_limit 机制、安全阀原理），代码中用 TODO(Task 2.6) 标注扩展点。Task 2.6 引入循环时，将 generate → END 改为条件边，同时添加安全阀节点——此时两者有真实的交互关系，代码才不是死代码。

**反事实自检**：

- [x] 方案 A 不再失效（如果当前图有循环），两方案都可行 → "当前图为线性流，无循环"正是让方案 A 的安全阀变成死代码的原因 → 验证通过

---

### 决策 4：greeting 节点的独立设计

**语境**：routing.py 定义了三个路由标签（RETRIEVE/GREETING/FALLBACK），但验收标准只提到"route → retrieve 或 fallback"。GREETING 标签应该路由到独立的 greeting 节点，还是复用 fallback 节点？

**候选对比**：

- **方案 A**：GREETING → 独立 greeting 节点 → END
  - 优势：用户体验好——问候得到友好回复而非"我无法回答"；语义清晰——greeting 是"打招呼"，fallback 是"无法回答"，两者含义不同；与 routing.py 的三个标签严格对齐
  - 硬伤：多一个节点和多一条边

- **方案 B**：GREETING → fallback 节点 → END
  - 优势：图结构更简单——只有两个分支（retrieve 和 fallback）
  - 硬伤：用户体验差——用户说"你好"得到"我无法回答"；语义错误——问候不是"无法回答"

**反驳推演**：方案 B 的用户体验不可接受——"你好" → "抱歉，我无法回答这个问题"在演示时会立即暴露问题。方案 A 多一个节点的成本极低（一个 5 行的函数 + 一条边），但用户体验提升显著。

**结论**：选 A。GREETING 路由到独立 greeting 节点。验收标准的"route → retrieve 或 fallback"是简化描述，不是约束——实际路由有三个分支。

**反事实自检**：

- [x] 方案 B 不再失效（如果 greeting 和 fallback 的回复内容可以统一），两方案都可行 → "问候回复和降级回复的语义和措辞完全不同"正是让方案 B 的合并失去合理性的原因 → 验证通过

---

### 质量准则豁免

| 维度 | 落地方式 |
|------|---------|
| 模块分离 | edges.py（路由函数）和 builder.py（图组装 + 简单节点）职责清晰 ✅ |
| 架构分层 | builder → factories（依赖创建）→ nodes（节点函数）→ edges（路由函数）✅ |
| SOLID | SRP: edges 只做路由选择；OCP: 新增路由分支只改 edges.py 的路由函数；DIP: build_graph 依赖 Settings ✅ |
| 封装与抽象 | build_graph 封装图构建细节，暴露 CompiledGraph 接口 ✅ |
| 设计模式 | 工厂模式（build_graph）✅ |
| 可观测性 | 日志记录图构建过程和编译结果 ✅ |
| 配置管理 | max_iterations 通过 Settings 集中管理 ✅ |
| 鲁棒性/容错 | route_after_classification 对无效 route_decision 默认 FALLBACK ✅ |
| 可测试性 | 路由函数是纯函数，可独立测试；build_graph 通过 mock factories 测试 ✅ |
| 可扩展性 | 图结构为 Task 2.6 的循环和安全阀预留 TODO 标注 ✅ |

无需豁免。

---

### 非关键决策

1. **`add_conditional_edges` 未传 `path_map`**：当前路由函数是简单 if-else，编译器可推断返回值。但放弃了编译期安全网——路由函数返回 `path_map` 外的节点名时，有 `path_map` 会编译失败，没有则运行时才报错。Task 2.6 新增 `tool_call` 分支时应补充 `path_map`。

2. **`_greeting_node` / `_fallback_node` 用下划线前缀**：意图标记"模块私有"。但测试文件直接 `from src.workflow.builder import _greeting_node`——下划线前缀与测试可导入性矛盾。不改为公开名是因为它们不是 workflow 包的公共 API（`__init__.py` 不导出），只是测试内部需要访问。

3. **`route_after_classification` 用 if-else 而非 dict dispatch**：三个分支时两种方式等价。如果后续新增 `tool_call` 分支（前瞻性约束 #8），if-else 会膨胀——届时应重构为 dict dispatch。当前不做，避免对三个分支的场景过度设计。

4. **`build_graph` 编译后日志仅记录"工作流图构建完成"**：缺少节点数/边数等结构信息。当前图结构固定，调试需求低。Task 2.6 图拓扑变化更大时，可补充结构信息。

---

## 模块结构

### 文件组织
```
src/workflow/
├── __init__.py      # 更新：导出 build_graph
├── state.py         # 不变
├── routing.py       # 不变
├── nodes.py         # 不变
├── edges.py         # 新增：条件边路由函数
└── builder.py       # 新增：图构建

src/core/
└── settings.py      # 更新：新增 max_iterations 字段
```

### 关键外部依赖（仅列非标准库）
```
edges.py
├── src.workflow.routing        # RETRIEVE, GREETING, FALLBACK 常量
└── src.workflow.state          # GraphState

builder.py
├── langgraph.graph             # StateGraph, START, END
├── langchain_core.messages     # AIMessage
├── src.core.settings           # Settings
├── src.core.factories          # create_retriever, create_llm
├── src.generation.prompts      # PromptVersion, get_prompt
├── src.workflow.nodes          # create_workflow_nodes
├── src.workflow.edges          # route_after_classification
├── src.workflow.routing        # RETRIEVE, GREETING, FALLBACK
└── src.workflow.state          # GraphState
```

### 职责边界
```
edges.py 职责：
✅ 包含：条件边路由函数（state -> 下一跳节点名）
✅ 包含：路由辅助常量
❌ 不包含：节点函数定义 ← 属于 nodes.py 或 builder.py
❌ 不包含：图构建逻辑 ← 属于 builder.py

builder.py 职责：
✅ 包含：build_graph(settings) 图构建函数
✅ 包含：简单终端节点定义（greeting_node, fallback_node）
✅ 包含：预设回复常量（GREETING_RESPONSE, FALLBACK_RESPONSE）
❌ 不包含：路由逻辑 ← 属于 edges.py
❌ 不包含：复杂节点逻辑 ← 属于 nodes.py
```

### 与后续 Task 的接口衔接
- Task 2.4：build_graph 将需要接受 checkpointer 参数（`build_graph(settings, checkpointer=...)`）
- Task 2.5：对话记忆不影响图拓扑，仅影响 messages 字段的内容
- Task 2.6：将 generate → END 改为 generate → should_continue → [END | retrieve | safety_valve]；route_after_classification 可能需要新增 tool_call 分支

---

## 面试知识点覆盖

### 1. add_node + add_edge + add_conditional_edges

图构建三部曲的执行顺序有严格约束：
1. **先添加所有节点**（`add_node`）：节点必须存在才能被边引用
2. **再连接边**（`add_edge` / `add_conditional_edges`）：边引用不存在的节点会编译失败
3. **条件边通过路由函数决定下一跳**：`add_conditional_edges(source, path_fn)` 中 `path_fn` 是纯函数，读取状态返回节点名

本项目的体现：
```python
# 第1步：添加所有节点
graph.add_node("route", nodes["route"])
graph.add_node("retrieve", nodes["retrieve"])
graph.add_node("generate", nodes["generate"])
graph.add_node("greeting", _greeting_node)
graph.add_node("fallback", _fallback_node)

# 第2步：连接边
graph.add_edge(START, "route")                          # 入口边
graph.add_conditional_edges("route", route_after_classification)  # 条件边
graph.add_edge("retrieve", "generate")                  # 固定边
graph.add_edge("generate", END)                         # 终止边
graph.add_edge("greeting", END)                         # 终止边
graph.add_edge("fallback", END)                         # 终止边
```

### 2. START 和 END 常量

- `START`：图的入口节点，不是用户定义的节点，是 LangGraph 的虚拟节点。所有图的执行从 START 开始。
- `END`：图的终止节点，也不是用户定义的节点。节点连接到 END 表示图执行结束。
- **必须显式连接**：如果不连接 START → 第一个节点，或最后一个节点 → END，图无法编译。

### 3. 循环与递归限制

- LangGraph 通过 `RunnableConfig` 的 `recursion_limit` 控制最大迭代次数，默认 25。
- 每次节点执行算一次迭代。如果迭代次数超过 `recursion_limit`，图抛出 `GraphRecursionError`。
- 设置方式：`graph.invoke(input, config={"recursion_limit": 10})`
- **当前项目**：Task 2.3 的图是线性的（无循环），recursion_limit 不会触发。Task 2.6 引入循环后，recursion_limit 是防止死循环的最后一道防线。
- **安全阀 vs recursion_limit 的区别**：
  - 安全阀是业务层的循环控制（`iteration_count >= max_iterations → 安全阀节点`），提供优雅降级（返回预设回复）
  - recursion_limit 是框架层的硬限制，触发时抛异常（`GraphRecursionError`），是应急保护而非优雅处理
  - 生产级系统应同时使用两者：安全阀作为正常控制流，recursion_limit 作为兜底保护

### 4. CompiledGraph

- `StateGraph.compile()` 将图定义转换为可执行的 `CompiledStateGraph`。
- 编译过程会验证：节点连接完整性（所有节点可达）、循环检测等。
- 编译后的图支持 `invoke`（同步调用）、`stream`（流式输出）、`astream`（异步流式）等运行方式。
- 编译是一次性操作，编译后的图可重复调用。

---

## 错误处理策略

| 异常/异常场景 | 处理方式 | 中断主流程？ | 理由 |
|------|---------|------------|------|
| route_decision 为空/无效 | route_after_classification 默认返回 FALLBACK | 否 | 安全降级：无效分类结果走降级路径 |
| 图编译失败 | build_graph 抛出原始异常（LangGraph 的错误信息已足够诊断） | 是 | 编译失败意味着图定义有误，不应静默忽略 |
| Settings 字段缺失 | Pydantic ValidationError 在 build_graph 调用前就抛出 | 是 | 快速失败原则 |

---

## 测试策略概要

### 可独立测试的函数/方法

- `route_after_classification(state)`：纯函数，给定 state["route_decision"] 验证返回正确的节点名
- `build_graph(settings)`：验证图编译成功、节点存在、边连接正确

### Mock 边界

- **factories 模块**：测试 build_graph 时 mock `create_retriever`、`create_llm`、`get_prompt` 返回 Mock 对象
- **Settings**：使用测试专用的 Settings 实例（不需要真实 API Key）

### 必须覆盖的关键测试场景

- **route_after_classification**：
  - route_decision="retrieve" → 返回 "retrieve"
  - route_decision="greeting" → 返回 "greeting"
  - route_decision="fallback" → 返回 "fallback"
  - route_decision="" → 返回 "fallback"（默认降级）
  - route_decision="unknown" → 返回 "fallback"（无效标签降级）
- **build_graph**：
  - 编译成功（无异常）
  - 图包含 5 个节点（route, retrieve, generate, greeting, fallback）
  - 条件边从 route 出发
  - generate → END 边存在
  - 可执行简单调用（mock 依赖，验证图能运行到 END）

---

## 代码蓝图：施工图纸级别

### edges.py

```python
"""条件边路由函数 — 根据状态决定图的执行路径。

本模块定义条件边的路由函数，这些函数读取 GraphState 中的特定字段，
返回下一跳节点名称。LangGraph 的 add_conditional_edges 使用这些函数
实现动态路由。

为什么路由函数独立为模块（设计决策）：
    1. 可测试性：路由函数是纯函数（state -> str），可独立测试
    2. 职责单一：edges.py 负责"路径选择"，builder.py 负责"图组装"
    3. 可替换性：Task 2.6 自适应路由可替换路由函数，图结构无需修改
"""
```

#### route_after_classification

```python
def route_after_classification(state: GraphState) -> str:
    """条件边路由函数：route 节点之后，根据 route_decision 决定下一跳。

    为什么是幂等函数（生产级注意事项）：
        给定相同的 state，此函数始终返回相同的标签。
        条件边的路由函数必须是幂等的——如果相同状态产生不同路由，
        会导致不可预测的执行路径和难以复现的 bug。

    为什么未知标签默认返回 FALLBACK 而非 RETRIEVE（与 classify_intent 的默认值不同）：
        classify_intent 默认 RETRIEVE 是"分类前的乐观回退"——
        还没分类就给检索一个机会。route_after_classification 默认 FALLBACK 是
        "分类后的保守回退"——route_node 已经尝试分类但产生了无效结果，
        说明分类流程出了问题，此时再走检索可能带着无效的 question 字段，
        不如直接降级。

    Args:
        state: 当前图状态

    Returns:
        下一跳节点名称："retrieve" / "greeting" / "fallback"
    """
    # 步骤 1：调用 dict.get，传入 "route_decision"，缺省 ""，返回 decision

    # 步骤 2：匹配路由标签
    #   ├─ RETRIEVE → "retrieve"
    #   ├─ GREETING → "greeting"
    #   ├─ FALLBACK → "fallback"
    #   └─ 未知/空 → "fallback"（保守降级）
```

---

### builder.py

```python
"""图构建模块 — 组装 LangGraph StateGraph 并编译为可执行图。

本模块定义 build_graph 函数，将路由/检索/生成/问候/降级节点组装为完整的问答工作流。

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
```

#### 预设回复常量

```python
GREETING_RESPONSE = "你好！我是文档问答助手，可以帮你解答与文档相关的问题。请问有什么我可以帮助你的？"
"""问候预设回复 — 独立于 fallback 回复，两者语义不同：
    greeting = "打招呼，引导用户提问"
    fallback = "无法回答，告知用户限制"
    两者措辞和语气完全不同，不应合并。"""

FALLBACK_RESPONSE = "抱歉，我无法回答这个问题。我的知识范围限于文档库中的内容，请尝试提出与文档主题相关的问题。"
"""降级预设回复 — 明确告知用户系统能力边界。"""
```

#### 终端节点函数

```python
def _greeting_node(state: GraphState) -> dict:
    """问候节点：返回预设问候回复。

    为什么是模块级函数而非闭包（功能取舍）：
        greeting 节点无需注入外部依赖（纯预设回复），
        模块级函数最简单。如果后续需要 LLM 生成动态问候，
        可改为闭包注入——但当前无此需求，不超前实现。
    """
    # 更新状态：{"messages": [AIMessage(content=GREETING_RESPONSE)]}（问候引导用户提问）

def _fallback_node(state: GraphState) -> dict:
    """降级节点：返回预设降级回复。"""
    # 更新状态：{"messages": [AIMessage(content=FALLBACK_RESPONSE)]}（明确告知能力边界）
```

#### build_graph

```python
def build_graph(settings: Settings) -> CompiledStateGraph:
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

    为什么 greeting 和 fallback 是模块级函数而非闭包（功能取舍）：
        这两个节点无需注入外部依赖（纯预设回复），模块级函数更简单。
        如果后续需要 LLM 生成问候回复，可改为闭包注入。

    为什么 generate 后用直接边而非条件边（设计决策）：
        当前图为线性流（无循环），generate 直接到 END 是最简洁的设计。
        Task 2.6 引入循环时，将 generate → END 改为条件边，
        添加 should_continue 路由函数和安全阀节点。

    Args:
        settings: 全局配置实例

    Returns:
        编译后的 CompiledStateGraph
    """
    # 步骤 1：通过 factories 创建三大依赖——注入方式（settings 驱动），后续切向量库/LLM 只需改配置
    #   调用 create_retriever，传入 settings，返回 retriever
    #   调用 create_llm，传入 settings.llm_provider + settings，返回 llm
    #   调用 get_prompt，传入 PromptVersion.V2 + include_few_shot=True，返回 prompt

    # 步骤 2：调用 create_workflow_nodes，传入 retriever/llm/prompt/max_iterations，返回 nodes
    #         注入：retriever、llm、prompt 均可 Mock

    # 步骤 3：创建 StateGraph，传入 GraphState 作为状态类型，返回 graph

    # 步骤 4：注册五个节点，每个 add_node 传入节点名称和对应函数
    #   4a：调用 graph.add_node，传入 "route" 和 nodes["route"]
    #   4b：调用 graph.add_node，传入 "retrieve" 和 nodes["retrieve"]
    #   4c：调用 graph.add_node，传入 "generate" 和 nodes["generate"]
    #   4d：调用 graph.add_node，传入 "greeting" 和 _greeting_node
    #   4e：调用 graph.add_node，传入 "fallback" 和 _fallback_node

    # 步骤 5：连接边（六条）
    #   5a：调用 graph.add_edge，传入 START 和 "route"——入口
    #   5b：调用 graph.add_conditional_edges，传入 "route" 和 route_after_classification——条件路由
    #   5c：调用 graph.add_edge，传入 "retrieve" 和 "generate"——检索到生成
    #   5d：调用 graph.add_edge，传入 "generate" 和 END——生成到结束
    #   5e：调用 graph.add_edge，传入 "greeting" 和 END——问候到结束
    #   5f：调用 graph.add_edge，传入 "fallback" 和 END——降级到结束
    # TODO(Task 2.6): 将 generate → END 改为条件边，添加安全阀

    # 步骤 6：调用 graph.compile() 编译，返回 compiled
    #         日志：info 记录图构建完成
    # 返回 compiled
```

---

## Settings 新增字段

```python
# 在 Settings 类中新增：
max_iterations: int = Field(
    default=3,
    description="工作流最大迭代次数（安全阀阈值，Task 2.6 条件边使用）",
)
```

为什么在 Task 2.3 添加（当前 max_iterations 只用于 create_workflow_nodes 的参数传递，尚无实际检查逻辑）：
  配置管理原则——max_iterations 是业务配置，应在 Settings 中集中管理。
  当前 build_graph 需要将其从 Settings 传递给 create_workflow_nodes，
  如果不添加到 Settings，build_graph 就需要硬编码默认值，违反"禁止硬编码"。

---

## 常见坑点

1. **add_conditional_edges 的路由函数返回值**：路由函数必须返回已注册的节点名称字符串或 `END` 常量。返回未注册的节点名会导致编译失败。`route_after_classification` 返回的 "retrieve"/"greeting"/"fallback" 必须与 `add_node` 注册的名称完全一致。

2. **START 和 END 的导入路径**：从 `langgraph.graph` 导入 `START` 和 `END`，不是从 `langgraph.graph.state` 导入。导入路径错误会导致 NameError。

3. **条件边的路由函数签名**：路由函数接受 `state: GraphState` 参数，不是 `state: dict`。虽然 TypedDict 运行时是 dict，但类型注解应使用 GraphState 以保持一致性。

4. **节点注册顺序 vs 边连接顺序**：所有 `add_node` 必须在 `add_edge` / `add_conditional_edges` 之前完成。边引用未注册的节点名会导致编译错误。

5. **compile() 的调用时机**：必须在所有节点和边添加完成后调用 `compile()`。在 `add_node`/`add_edge` 之间调用 compile 会导致部分节点/边缺失。

6. **greeting 和 fallback 节点也需要连接到 END**：如果忘记将 greeting/fallback 连接到 END，这些路径会成为死胡同——图执行到这些节点后无法结束，导致运行时错误。
