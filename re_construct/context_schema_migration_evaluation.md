# Workflow context_schema 迁移评估

## 1. 背景

context_schema 是 LangGraph 提供的**运行时配置注入机制**，用于向图节点传递不属于图状态的每次调用级配置。当前 Workflow 路径中，`max_iterations`（最大迭代次数，用于 Task 2.6 安全阀）作为工厂期参数传入 `create_workflow_nodes`，而非通过 context_schema 在 invoke 时注入。

### 偏差本质

```text
LangGraph 预期模式：
  settings → GraphContext(max_iterations=N) → invoke(context=GraphContext(...))
                                                 ↓
  node(runtime) 读取 runtime.context.max_iterations
                        ↓
                运行时可变，每次 invoke 可独立配置

当前 Workflow 模式：
  settings.max_iterations → create_workflow_nodes(max_iterations=N) → 闭包固定
                                                                      ↓
                        generate_node 内部闭包引用，invoke 时无法变更
                        max_iterations 被锁定在工厂期的值
```

### 技术债务时间线

```text
Task 2.3 (图构建+安全阀)：  max_iterations 作为 Settings 字段            → 合理（配置集中管理）
                         build_graph → create_workflow_nodes 传参      → 开始偏离
Task 2.5 (记忆管理)：       需要引入新运行时参数（max_tokens, keep_recent）→ 暴露矛盾
                         现有模式 → 每个运行时参数都作为工厂参数传递       → scales poorly
```

关键偏差点：`max_iterations` 语义上是**运行时配置**（不同 invoke 可能需要不同阈值），却被绑定到**工厂参数**的生命周期。当前项目只在 `create_workflow_nodes` 有一个运行时参数，Task 2.5 会新增至少 3 个（`memory_max_tokens`、`memory_keep_recent`、`memory_summary_enabled`），偏差将急剧放大。

---

## 2. 当前架构分析

### 2.1 参数生命周期错配

当前 `create_workflow_nodes` 的参数按职责可分为两类：

| 参数 | 语义类型 | 实际生命周期 | 应属生命周期 | 错配 |
|------|---------|-------------|-------------|------|
| `retriever` | 服务依赖 | 进程/图级 | 进程/图级 | 无 |
| `llm` | 服务依赖 | 进程/图级 | 进程/图级 | 无 |
| `citation_extractor` | 服务依赖 | 进程/图级 | 进程/图级 | 无 |
| **`max_iterations`** | **运行时配置** | **工厂期固定** | **invoke 期可变** | **有** |

`max_iterations` 与 `retriever` 放在同一参数列表中，但它们的生命周期完全不同：
- `retriever` 只要向量库不变就不需要换
- `max_iterations` 理论上每次 invoke 都可能不同（如生产 3 次，调试 10 次）

### 2.2 当前调用链

```text
settings.max_iterations
           ↓
build_graph(settings)                    # 读取配置
    → create_workflow_nodes(retriever, llm, max_iterations=settings.max_iterations)
    → def generate_node(state):
          # max_iterations 被闭包捕获，无法在 invoke 时覆盖
          # 当前只存不用，Task 2.6 做条件边检查
    → StateGraph(GraphState)              # 未注册 context_schema
    → graph.compile()
           ↓
app.py → graph.invoke(inputs)            # 无 context 参数可传
```

### 2.3 记忆管理引入后的参数膨胀

Task 2.5 记忆管理需要引入的新参数（来自 task_2.5_scan.md）：

| 参数 | D9 候选项 |
|------|----------|
| 触发摘要的 token 阈值 | 建议 4000 |
| 保留的最近消息数 | 建议 2-4 |
| 是否启用摘要（vs 仅裁剪） | 布尔开关 |

若继续当前模式，`create_workflow_nodes` 会演变为：

```python
def create_workflow_nodes(
    retriever: RetrieverProtocol,
    llm: BaseChatModel,
    citation_extractor: CitationExtractor | None = None,
    max_iterations: int = 3,
    memory_max_tokens: int = 4000,       # 新增
    memory_keep_recent: int = 4,         # 新增
    memory_summary_enabled: bool = True, # 新增
) -> dict[str, Callable]:
    # 7 个参数混在一起，服务依赖与运行时配置不分
```

context_schema 将这些运行时配置移到 invoke 时传入，工厂参数只保持真正的服务依赖。

---

## 3. 修正方案的设计误区

### 3.1 初步设计（有问题的关注点）

初步思考时容易陷入以下误区：

```text
误区 1：max_iterations 当前没有消费者，迁移没有价值
  反驳：Task 2.6 会作为条件边检查消费它。现在迁移是"先铺管道，等不通了再修"
        vs "现在铺好，Task 2.6 直接接"的区别。更关键的是 Task 2.5 的新参数
        会复用电线管道，迁移的实际价值在复用而非单参数。

误区 2：把 GraphContext 放在单独文件 context.py
  反驳：GraphContext 是 Schema 定义，与 GraphState 同属"状态/配置类型"的关注点。
        放在 state.py 中，一个文件管理所有与图相关的类型。单独文件增加导航成本，
        且内容（一个 dataclass）不值得一个文件。

误区 3：所有节点都加上 runtime 参数
  反驳：只有实际消费者才加。当前只有 generate_node 需要 max_iterations，
        route_node 和 retrieve_node 不需要。不超前注入，保持最小接口。
```

### 3.2 两个技术陷阱

**陷阱 1：`runtime.context` 为 None 时的处理策略不当**

```python
# 激进的版本（有风险）：
def generate_node(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
    assert runtime.context is not None, "context 是必需的"
    max_iterations = runtime.context.max_iterations

# 存在的问题：
# - context_schema 定义后，invoke 不传 context 是合法操作
# - assert 导致调用方必须传 context，违反"可选"语义
# - 当前没有外部调用方，但 Task 2.7 引入 CLI 时可能忘记传 context

# 更稳的版本（推荐）：
def generate_node(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
    if runtime.context is not None:
        max_iterations = runtime.context.max_iterations
    else:
        max_iterations = 3  # 硬编码兜底
```

**陷阱 2：调用方契约模糊**

`build_graph` 当前返回 `CompiledStateGraph`，调用方用它做 `invoke`。引入 context_schema 后，调用方需要知道要传 `context=GraphContext(max_iterations=...)`。

谁负责构造 `GraphContext` 实例？有两种方向：

```text
方向 A：builder 构造默认实例，记录在 docstring 中
  graph = build_graph(settings)
  # 调用 invoke 时建议传 context
  result = graph.invoke(inputs, context=GraphContext(max_iterations=3))

方向 B：builder 绑定默认值到编译后的图
  不现实——context_schema 的值只能在 invoke 时传入，没有"编译期绑定"机制

推荐方向 A
```

---

## 4. 影响范围

### 4.1 修改的文件（5 个）

**`src/workflow/state.py`**（+1 dataclass）

| 改动项 | 说明 |
|--------|------|
| 新增 `GraphContext` dataclass | 一个字段 `max_iterations: int = 3` |
| 导出 `GraphContext` | 加入 `__all__` |

**`src/workflow/nodes.py`**（~10 行修改）

| 改动项 | 当前 | 修正后 |
|--------|------|--------|
| `create_workflow_nodes` 签名 | `(retriever, llm, citation_extractor, **max_iterations**)` | `(retriever, llm, citation_extractor)` — 移除 `max_iterations` |
| 导入新增 | — | `from langgraph.runtime import Runtime`; `from .state import GraphContext` |
| `generate_node` 签名 | `def generate_node(state: GraphState) -> dict` | `def generate_node(state: GraphState, runtime: Runtime[GraphContext]) -> dict` |
| generate 内部 | 闭包引用 `max_iterations` | `runtime.context.max_iterations if runtime.context is not None else 3` |

**`src/workflow/builder.py`**（~3 行修改）

| 改动项 | 当前 | 修正后 |
|--------|------|--------|
| 导入新增 | — | `from .state import GraphContext` |
| StateGraph 注册 | `StateGraph(GraphState)` | `StateGraph(GraphState, context_schema=GraphContext)` |
| `create_workflow_nodes` 传参 | `nodes = create_workflow_nodes(..., max_iterations=settings.max_iterations)` | `nodes = create_workflow_nodes(...)` — 删除 `max_iterations` |

**`src/workflow/__init__.py`**（+1 导出）

```python
from .state import GraphContext

__all__ = [
    "GraphState",
    "GraphContext",     # 新增
    "build_graph",
    ...
]
```

**`tests/test_workflow_nodes.py`**（~5 处修改）

| 改动项 | 说明 |
|--------|------|
| `create_workflow_nodes(mock_retriever, llm)` | 参数减少，调用处无需改动 |
| `nodes["generate"](state)` → `nodes["generate"](state, runtime)` | 所有 generate_node 测试需要传入 runtime |
| test fixture 新增 | `Runtime(context=GraphContext(max_iterations=3))` 作为公共 fixture |

### 4.2 未修改的文件

| 文件 | 原因 |
|------|------|
| `src/workflow/routing.py` | 意图分类逻辑不变，不感知 context |
| `src/workflow/edges.py` | 条件边路由函数不变，不感知 context |
| `src/workflow/prompts.py` | 模板管理不变，不依赖运行时配置 |
| `src/workflow/citation.py` | 引用提取不变，不依赖运行时配置 |
| `src/workflow/checkpointer.py` | 检查点管理不变 |
| `src/core/settings.py` | `max_iterations` **保留**——作为生成默认 context 的源值 |
| `src/app.py` | 使用 RAGChain，不涉及 Workflow |
| `src/generation/` 全部 | 完全不碰 |

### 4.3 修正后的数据流

```text
迁移前（工厂期固定）：

  settings.max_iterations=3 ──────────────────────────┐
                                                      ↓
  build_graph(settings) → create_workflow_nodes(max_iterations=3)
                              → generate_node 闭包捕获 max_iterations=3
                                      ↓
  graph.invoke(inputs)  # 无法覆盖，始终 3

迁移后（运行时注入）：

  settings.max_iterations=3           ← 保留，作为默认值来源
        ↓
  build_graph(settings)
      → StateGraph(GraphState, context_schema=GraphContext)  ← 只注册类型
                                      ↓
  graph.invoke(inputs, context=GraphContext(max_iterations=3))
                                      ↓
  generate_node(state, runtime) → runtime.context.max_iterations
                                      ↓
  可覆盖：graph.invoke(inputs, context=GraphContext(max_iterations=10))  # 调试时
```

### 4.4 模块依赖关系

```text
迁移前：
  workflow/builder.py → workflow/nodes.py → state.py (GraphState)
  workflow/nodes.py   → state.py (GraphState)

迁移后：
  workflow/builder.py → workflow/nodes.py → state.py (GraphState + GraphContext)
  workflow/nodes.py   → state.py (GraphState + GraphContext)
  workflow/builder.py → langgraph.graph (StateGraph 的 context_schema 参数)

无新增模块依赖，完全在 workflow 包内部闭环。
```

---

## 5. 深度审查补充发现

### 5.1 `settings.max_iterations` 的去留

`max_iterations` 进 `context_schema` 后，`settings.py` 中的同名字段是否应删除？

| 选项 | 影响 |
|------|------|
| **A: 保留**（推荐） | builder 在内部使用 `GraphContext(max_iterations=settings.max_iterations)` 作为默认值。调用方（将来的 app.py）不传 context 时代码退化到当前行为。**留是向下兼容** |
| **B: 删除** | settings.py 减少一个字段。但 builder 需要硬编码默认值（3），与 settings 解耦但失去"统一配置源" |

**推荐 A**：settings 保留 `max_iterations` 作为**默认 context 的配置源**。语义从"直接传给工厂的参数"变为"构建默认 context 的源值"——用途变了，但配置集中管理的原则不变。删除它反而会导致 builder 硬编码。

### 5.2 节点签名风格的一致性

当前节点签名模式有 3 种变体：

```python
# 变体 1：只读 state（greeting, fallback 终端节点）
def _greeting_node(state: GraphState) -> dict:

# 变体 2：state + runtime（generate_node 修正后）
def generate_node(state: GraphState, runtime: Runtime[GraphContext]) -> dict:

# 变体 3：state + config + runtime（极少数场景）
def node(state: GraphState, config: RunnableConfig, runtime: Runtime[GraphContext]) -> dict:
```

LangGraph 不要求所有节点签名一致——只需要每个节点的签名被框架正确匹配。上述三种变体在同一个图中可以共存。所以：

- 只给 generate_node 加 `runtime`
- route_node 和 retrieve_node 保持现状

不强制统一，不引入不需要的参数。

### 5.3 context_schema 与 Store 的关系

context_schema 的 `Runtime` 对象还携带 `store` 字段（`BaseStore` 实例）。当前项目暂未使用 store（Task 4.x 可能引入）。迁移 context_schema 后，节点函数签名中已经出现了 `Runtime[GraphContext]`，后续引入 store 访问时无需再次修改签名——store 作为 `runtime.store` 直接可用。

这是一个**顺手打开的接口**，不是"超前设计"——`Runtime` 参数已经在签名中，store 字段是 `Runtime` 的内置属性，不额外产生复杂度。

---

## 6. 收益与成本

### 6.1 收益

1. **生命周期对齐** — `max_iterations` 从工厂期固定变为 invoke 期可变，语义与 LangGraph 模型一致
2. **Task 2.5 参数复用** — memory 的新参数（`memory_max_tokens`、`memory_keep_recent`、`memory_summary_enabled`）直接进 `GraphContext`，不走工厂参数膨胀
3. **与 LangGraph 官方模式对齐** — 图节点通过 `Runtime` 读取运行时配置，是 LangGraph 的标准做法
4. **测试便利** — 不同的测试案例可以在 invoke 时传不同的 `GraphContext`，无需重建图
5. **路径最短** — 全部在 workflow 包内闭环，不涉及外部模块

### 6.2 成本

1. **修改范围**：5 个文件（3 源码 + 1 init + 1 测试），~30 行净改动
2. **null-safe 样板代码**：`runtime.context` 为 None 时的兜底逻辑
3. **调用方知识负担**：调用 invoke 时需要知道传 `context` 参数
4. **settings.max_iterations 保持死字段**：保留但语义从"直接传参"变为"默认值源"，需要文档说明

### 6.3 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| `runtime.context is None` 时静默使用默认值 | 低 | 日志 warning 记录无 context 但使用默认值 |
| 现有测试中 generate_node 签名变化导致调用失败 | 中 | 逐处更新测试调用，注入 `Runtime(context=GraphContext())` |
| 调用方不知需要传 context | 低 | `build_graph` docstring 注明建议传 context |
| Task 2.5 需确认字段追加 | 低 | context_schema 设计为 dataclass，追加字段不改签名 |
| 与现有 `config` 参数混淆 | 低 | `context` 和 `config` 是不同参数，LangGraph 在 invoke 签名中明确区分 |

---

## 7. 与后续 Task 的衔接

### 7.1 执行顺序

```
本次迁移 → Task 2.5（记忆管理）→ Task 2.6（自适应路由）
```

本次迁移独立于 Task 2.5，可以先回顾再做。完成后的状态：

```text
迁移完成后可用接口：
  GraphState              → TypedDict（状态 schema）
  GraphContext            → dataclass（运行时配置 schema）
  build_graph(settings)   → 注册 context_schema + 创建默认 context
  graph.invoke(inputs, context=GraphContext(...))
```

### 7.2 Task 2.5 中的使用

Task 2.5 增加记忆管理参数时，只需在 `GraphContext` 追加字段：

```python
@dataclass
class GraphContext:
    max_iterations: int = 3
    memory_max_tokens: int = 4000          # Task 2.5 追加
    memory_keep_recent: int = 4            # Task 2.5 追加
    memory_summary_enabled: bool = True    # Task 2.5 追加
```

memory 节点通过 `runtime.context.memory_max_tokens` 读取阈值，无需修改工厂函数签名。

### 7.3 Task 2.6 中的使用

Task 2.6 的自适应路由同样通过 `runtime.context` 读取配置，不需要修改节点函数的参数列表。

```python
def should_continue(state: GraphState, runtime: Runtime[GraphContext]) -> str:
    if state["iteration_count"] >= runtime.context.max_iterations:
        return "__END__"
    # ... 自信度评估逻辑
    return "retrieve"
```

Task 2.5 和 2.6 都依赖 `GraphContext` 的字段存在，而不依赖字段的**获取方式**——这正是 context_schema 的核心价值：运行时配置与节点逻辑解耦。

---

## 8. 决策建议

如果满足以下条件（当前为是），建议现在迁移 context_schema：

1. **Task 2.5 将在本次项目推进中实施** — 复用管道，降低整体修改量
2. **工厂参数中混有运行时配置** — 当前仅有 1 个，Task 2.5 至少新增 3 个，偏差加速扩大
3. **修改范围可控** — 30 行净改动，全部在 workflow 包内闭环

迁移后 `create_workflow_nodes` 的签名中将永久只有**服务依赖**参数，所有**运行时配置**都走 `GraphContext`，这是一个清晰、可持续的分界线。
