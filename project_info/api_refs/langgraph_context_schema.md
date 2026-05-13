# LangGraph context_schema 运行时配置机制

> 基于 LangGraph v1.1.10 验证，`context_schema` 参数自 v1.0 起取代已弃用的 `config_schema`。
> `Runtime` 类自 v0.6.0 引入，v1.0+ 与 `context_schema` 参数名统一为正式 API。
> 验证日期：2026-05-13，实际运行测试通过。

---

## 一、核心概念

### 1.1 定位

`context_schema` 是 LangGraph 提供的**运行时配置注入机制**，用于向图节点传递**不属于图状态**的每次调用级配置。类比：
- **State**: 节点间传递的数据（有 Reducer，被 Checkpoint 持久化）
- **config (RunnableConfig)**: LangGraph 框架级配置（thread_id, recursion_limit）
- **context**: 应用级运行时配置（user_id, 模型名, token 阈值等）

### 1.2 生命周期

```
context 生命周期: invoke/stream 调用开始 → 传递给 Runtime → 调用结束即销毁
                         ↓
                    NOT 被 checkpointer 持久化
                         ↓
                    每次 invoke 都需要独立传入
```

### 1.3 context_schema 在 LangGraph 三层上下文中的位置

`context_schema` 是 LangGraph **Context Engineering** 三层体系中的**静态运行时上下文**层。官方按"可变性 × 生命周期"两个维度划分：

| 上下文类型 | 描述 | 可变性 | 生命周期 | 访问方式 |
|---|---|---|---|---|
| **Static runtime context** | 用户元数据、DB 连接等一次性传入的依赖 | 静态 | 单次调用 | `context` 参数 → `Runtime.context` |
| **Dynamic runtime context** | 对话历史、中间结果等运行时演化数据 | 动态 | 单次调用 | LangGraph state 对象 |
| **Dynamic cross-conversation context** | 跨会话持久化数据（用户画像、偏好） | 动态 | 跨会话 | LangGraph `BaseStore` |

其中 `context_schema` 负责第一层——它是**依赖注入机制**，而非业务数据存储。官方特别强调：Runtime context 不是 LLM context window 或 prompt 中的上下文，而是**向节点/工具/middleware 注入运行时依赖**的类型化通道。

---

## 二、定义 context_schema

### 2.1 方式一：@dataclass（推荐）

```python
from dataclasses import dataclass

@dataclass
class GraphContext:
    user_id: str = "default_user"          # 带默认值
    model_provider: str = "deepseek"       # 带默认值
    max_tokens: int = 4000                 # 带默认值
    memory_enabled: bool = True            # 带默认值
```

**优点**：属性访问 `runtime.context.user_id`，比 `["user_id"]` 更简洁、IDE 补全友好。
**注意**：默认值只在使用 `context=GraphContext()` 时生效。不传 context 则 `runtime.context` 为 `None`。

### 2.2 方式二：TypedDict

```python
from typing import TypedDict

class GraphContext(TypedDict):
    user_id: str       # 无默认值，调用时必须提供所有字段
    model_provider: str
    max_tokens: int
```

**访问方式**：`runtime.context["user_id"]`
**缺点**：无默认值支持（除非 `total=False`），属性访问需用 dict 语法。

### 2.3 选择指导

| 特征 | @dataclass | TypedDict |
|------|-----------|-----------|
| 默认值 | ✓ 原生支持 | 需 `total=False` |
| 访问语法 | `ctx.field` | `ctx["field"]` |
| 类型检查 | ✓ | ✓ |
| Pydantic 校验 | 需额外处理 | 需额外处理 |

---

## 三、图构建时注册

```python
from langgraph.graph import StateGraph, START, END
from dataclasses import dataclass

@dataclass
class GraphContext:
    max_tokens: int = 4000

builder = StateGraph(
    state_schema=MyState,
    context_schema=GraphContext,    # ← 注册 context_schema
)
```

签名验证（源码确认）：

```python
def __init__(
    self,
    state_schema: type[StateT],
    context_schema: type[ContextT] | None = None,   # v0.6.0+
    *,
    input_schema: type[InputT] | None = None,
    output_schema: type[OutputT] | None = None,
) -> None: ...
```

**弃用说明**：`config_schema` 参数已废弃（v1.0+ 发出 DeprecationWarning），统一使用 `context_schema`。

---

## 四、在节点函数中访问

### 4.1 节点函数签名模式

LangGraph 通过**函数参数名称+类型注解**自动注入：

```python
def node(state: State) -> dict:
    """模式1：无 context — 节点不感知 Runtime"""
    ...

def node(state: State, runtime: Runtime[GraphContext]) -> dict:
    """模式2：state + runtime — 推荐"""
    threshold = runtime.context.max_tokens  # 或 runtime.context["max_tokens"]
    ...

def node(state: State, config: RunnableConfig, runtime: Runtime[GraphContext]) -> dict:
    """模式3：state + config + runtime — 全部注入"""
    thread_id = config["configurable"]["thread_id"]
    threshold = runtime.context.max_tokens
    ...
```

**已验证的模式**（实际运行测试通过）：
- `(state)` ✓
- `(state, runtime: Runtime[Ctx])` ✓
- `(state, config: RunnableConfig, runtime: Runtime[Ctx])` ✓
- `(state, config: RunnableConfig)` ✓

**不能用的模式**：
- `(runtime: Runtime[Ctx])` ✗ — LangGraph 强制传 state 作为第一个参数

### 4.2 Null 安全

即使 context_schema 已定义 + dataclass 有默认值，**不传 context 时 `runtime.context` 为 None**：

```python
# 安全模式
def node(state: State, runtime: Runtime[GraphContext]) -> dict:
    if runtime.context is None:
        max_tokens = 4000  # 硬编码兜底
    else:
        max_tokens = runtime.context.max_tokens
    ...

# 激进的模式（要求调用方必须传 context）
def node(state: State, runtime: Runtime[GraphContext]) -> dict:
    assert runtime.context is not None, "context 是必需的"
    max_tokens = runtime.context.max_tokens
    ...
```

---

## 五、调用时传入 context

所有图调用方法均支持 `context` 参数：

```python
# invoke
result = graph.invoke(inputs, context=GraphContext(user_id="alice"))

# stream
for chunk in graph.stream(inputs, context=GraphContext(user_id="bob")):
    ...

# astream
async for chunk in graph.astream(inputs, context=GraphContext(user_id="charlie")):
    ...

# 不传 context（runtime.context 为 None）
result = graph.invoke(inputs)
```

### 5.1 签名确认

```python
# CompiledStateGraph.invoke 签名
def invoke(
    self,
    input: InputT | Command | None,
    config: RunnableConfig | None = None,
    *,
    context: ContextT | None = None,      # ← 关键字参数
    stream_mode: StreamMode = "values",
    ...
) -> dict | Any: ...

# CompiledStateGraph.stream / astream 签名相同
```

### 5.2 context vs config 的区别

```python
# config — LangGraph 框架配置（thread_id 必须在这里）
graph.invoke(
    inputs,
    config={"configurable": {"thread_id": "xxx"}},  # 框架级
    context=GraphContext(user_id="alice"),            # 应用级
)
```

两个关键差异：
1. **命名空间不同**：config 用 `configurable` dict，context 是类型化 schema
2. **目的不同**：config 是 LangGraph 内部机制（checkpointer、recursion_limit），context 是应用业务配置

---

## 六、Runtime 类完整 API

> 源码位于 `langgraph.runtime.Runtime`，`v0.6.0` 引入。

```python
@dataclass
class Runtime(Generic[ContextT]):
    """Convenience class that bundles run-scoped context and other runtime utilities."""

    context: ContextT = field(default=None)
    """静态上下文，如 user_id、db_conn 等。可视为"每次运行的依赖"。"""

    store: BaseStore | None = field(default=None)
    """LangGraph 持久化存储。用于跨 thread 的记忆存取。"""

    stream_writer: StreamWriter = field(default=_no_op_stream_writer)
    """自定义流写入器。"""

    previous: Any = field(default=None)
    """上一次调用的返回值（仅 functional API + checkpointer 时可用）。"""

    execution_info: ExecutionInfo | None = field(default=None)
    """当前节点运行的只读元数据。在任务准备填充前为 None。

    子字段（官方确认，langgraph>=1.1.5）：
        .thread_id: int | None       — 当前线程 ID
        .run_id: str | None          — 当前运行 ID
        .attempt_number: int | None  — 当前重试次数
    """

    server_info: ServerInfo | None = field(default=None)
    """LangGraph Server 注入的元数据。开源 LangGraph 下为 None。

    子字段（官方确认，仅 LangGraph Server 环境有值）：
        .assistant_id: str | None  — Assistant ID
        .graph_id: str | None      — Graph ID
        .user: dict | None         — 认证用户信息，含 .identity
        .session_id: str | None    — 会话 ID
    """

    def merge(self, other: Runtime[ContextT]) -> Runtime[ContextT]:
        """合并两个 Runtime，优先使用 other 的非空值。"""

    def override(self, **overrides) -> Runtime[ContextT]:
        """替换指定字段，返回新 Runtime。"""

    def patch_execution_info(self, **overrides) -> Runtime[ContextT]:
        """替换 execution_info 的指定字段，返回新 Runtime。"""
```

---

## 七、用例模式

### 7.1 按 user_id 个性化

```python
@dataclass
class Ctx:
    user_id: str

def personalized_greeting(state: State, runtime: Runtime[Ctx]) -> State:
    user_id = runtime.context.user_id
    return {"response": f"Hello {user_id}!"}

graph = StateGraph(State, context_schema=Ctx).compile()
graph.invoke({}, context=Ctx(user_id="alice"))
```

### 7.2 运行时选择 LLM

```python
@dataclass
class Ctx:
    model_provider: str = "deepseek"

MODELS = {
    "deepseek": init_chat_model("deepseek-chat"),
    "qwen": init_chat_model("qwen-max"),
}

def call_model(state: MessagesState, runtime: Runtime[Ctx]) -> dict:
    model = MODELS[runtime.context.model_provider]
    response = model.invoke(state["messages"])
    return {"messages": [response]}
```

### 7.3 context + store 组合（跨 thread 记忆）

```python
@dataclass
class Ctx:
    user_id: str

async def call_model(
    state: MessagesState,
    runtime: Runtime[Ctx],
) -> dict:
    user_id = runtime.context.user_id
    namespace = ("memories", user_id)
    memories = await runtime.store.asearch(namespace, ...)
    # ... 使用 memories 增强 prompt
```

---

## 八、create_agent 与 middleware 中的 context_schema

> 官方文档确认：`context_schema` 不限于 `StateGraph`——`create_agent` 的 tools 和 middleware 同样通过依赖注入拿到 `Runtime[Context]`。

### 8.1 create_agent 注册

```python
from langchain.agents import create_agent

@dataclass
class Context:
    user_name: str

agent = create_agent(
    model="claude-sonnet-4-6",
    tools=[...],
    context_schema=Context,       # ← 注册方式与 StateGraph 相同
)

agent.invoke(
    {"messages": [{"role": "user", "content": "hi"}]},
    context=Context(user_name="John Smith"),
)
```

### 8.2 Middleware 中访问 Runtime

middleware hook 通过参数名注入 `Runtime`：

```python
from langchain.agents.middleware import dynamic_prompt, before_model

@dynamic_prompt
def system_prompt(request: ModelRequest) -> str:
    user_name = request.runtime.context.user_name  # ← 通过 Request 访问
    return f"Assistant, address the user as {user_name}."

@before_model
def log_request(state: AgentState, runtime: Runtime[Context]) -> dict | None:
    print(f"User: {runtime.context.user_name}, Thread: {runtime.execution_info.thread_id}")
    return None
```

### 8.3 工具中访问 Runtime

工具函数通过 `ToolRuntime[Context]` 参数获取：

```python
from langchain.tools import tool, ToolRuntime

@dataclass
class Context:
    user_id: str

@tool
def fetch_preferences(runtime: ToolRuntime[Context]) -> str:
    """获取用户偏好。"""
    uid = runtime.context.user_id
    if runtime.store:
        memory = runtime.store.get(("users",), uid)
        return memory.value["preferences"] if memory else "default"
    return "default"
```

### 8.4 对比总结

`create_agent` 的场景下 `context_schema` 的可达性更广，但核心机制一致：

| 消费者 | 获取方式 | 典型用途 |
|---|---|---|
| StateGraph 节点 | `runtime: Runtime[Ctx]` 参数 | 模型选择、阈值控制 |
| Middleware hook | `runtime: Runtime[Ctx]` 或 `request.runtime` | 动态 prompt、鉴权门禁 |
| Tool | `runtime: ToolRuntime[Ctx]` 参数 | 基于 user_id 的个性化数据访问 |

---

## 九、与现有 Pydantic Settings 的分工对比

| 特性 | Pydantic Settings | context_schema |
|------|------------------|----------------|
| 加载时机 | 启动时 | invoke 时 |
| 变更频次 | 不变（环境级） | 每次调用可变 |
| 存储位置 | .env / 环境变量 | 调用方显式传入 |
| 类型校验 | Pydantic ValidationError | dataclass 隐式校验 |
| 内容示例 | API Key、DB 路径、模型名 | user_id、阈值、功能开关 |
| 生命周期 | 进程级 | 调用级 |
| Checkpoint | N/A | 不被持久化 |

**推荐分工**：

```
Pydantic Settings: API Key、Base URL、向量库路径、模型名（固定配置）
context_schema:    user_id、max_tokens、keep_recent、memory_enabled（运行时可变）
模块常量:           很少变化的业务数字（如默认 4000 token 阈值）
```

---

## 十、关键行为总结

1. **`context_schema` 定义后，`context` 参数在 invoke 时仍是可选的** — `runtime.context` 可能为 `None`
2. **即使 dataclass 有默认值，不传 context 时 `runtime.context` 仍是 None** — 默认值只在 `context=MyCtx()` 时生效
3. **context 不被 checkpointer 持久化** — 每次 invoke 是独立上下文
4. **context_schema 是 v0.6.0 引入的** — 旧版 `config_schema` 已弃用
5. **节点通过函数签名自动获 Runtime** — 不需要手动创建或传递
6. **一个图只能有一个 context_schema** — 所有字段定义在一个类型中

---

## 十一、验证测试

以下行为已通过实际运行测试验证（`langgraph` 已安装版本）：

- `StateGraph(State, context_schema=Ctx)` 编译通过
- `node(state, runtime: Runtime[Ctx])` 正确注入 `runtime.context`
- `node(state, config: RunnableConfig, runtime: Runtime[Ctx])` 同时注入 config + context
- `context` 不传时 `runtime.context is None`
- TypedDict 和 dataclass 两种 context_schema 均可工作
- `context_schema` 定义后，不感知 runtime 的普通节点仍可正常工作
- `context=Ctx()`（全默认值）正常填充 dataclass 默认值

---

*`context_schema` 参数自 v1.0 起为正式 API。`Runtime` 类自 v0.6.0 引入。*
