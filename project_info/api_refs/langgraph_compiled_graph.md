# LangGraph CompiledStateGraph API 参考

> 版本：langgraph v1.1.10 | 来源：site-packages 源码确认
> v2 streaming 另有独立文档：`langgraph_v2_streaming.md`
> **信任此文档**

## 类继承链

```
Runnable[InputT, Any]
  └── PregelProtocol[StateT, ContextT, InputT, OutputT]   (protocol.py)
        └── Pregel[StateT, ContextT, InputT, OutputT]     (pregel/main.py)
              └── CompiledStateGraph[StateT, ContextT]    (graph/state.py)
```

## CompiledStateGraph 构造

由 `StateGraph.compile()` 返回，不直接实例化。

```python
graph = builder.compile(
    checkpointer: Checkpointer | None = None,
    *,
    cache: BaseCache | None = None,
    store: BaseStore | None = None,
    interrupt_before: All | Sequence[str] | None = None,
    interrupt_after: All | Sequence[str] | None = None,
    debug: bool = False,
    name: str | None = None,
)
```

## 核心方法

### 执行类

| 方法 | 同步 | 异步 | 返回类型 |
|------|------|------|----------|
| invoke | ✅ | `ainvoke` | `dict[str, Any] \| Any` |
| stream | ✅ | `astream` | `Iterator[dict[str, Any] \| Any]` |

> v2 模式：invoke → `GraphOutput`、stream → `Iterator[StreamPart]`（见 `langgraph_v2_streaming.md`）

**invoke 签名：**
```python
def invoke(
    self,
    input: InputT | Command | None,
    config: RunnableConfig | None = None,
    *,
    context: ContextT | None = None,          # v1.1.2 为远程图 API 新增（并非 config_schema 替代）
    stream_mode: StreamMode = "values",       # 返回模式
    print_mode: StreamMode | Sequence[StreamMode] = (),
    output_keys: str | Sequence[str] | None = None,
    interrupt_before: All | Sequence[str] | None = None,
    interrupt_after: All | Sequence[str] | None = None,
    durability: Durability | None = None,     # [不确定版本] "sync"|"async"|"exit"
    version: Literal["v1", "v2"] = "v1",     # v1.1 新增: v2 返回 StreamPart
    **kwargs: Any,
) -> dict[str, Any] | Any:
```

**stream 签名：**
```python
def stream(
    self,
    input: InputT | Command | None,
    config: RunnableConfig | None = None,
    *,
    context: ContextT | None = None,
    stream_mode: StreamMode | Sequence[StreamMode] | None = None,
    print_mode: StreamMode | Sequence[StreamMode] = (),
    output_keys: str | Sequence[str] | None = None,
    interrupt_before: All | Sequence[str] | None = None,
    interrupt_after: All | Sequence[str] | None = None,
    durability: Durability | None = None,
    subgraphs: bool = False,                  # v1.1: 返回子图事件
    debug: bool | None = None,
    version: Literal["v1", "v2"] = "v1",
    **kwargs: Any,
) -> Iterator[dict[str, Any] | Any]:
```

### 状态管理类

| 方法 | 同步 | 异步 | 返回类型 |
|------|------|------|----------|
| get_state | ✅ | `aget_state` | `StateSnapshot` |
| get_state_history | ✅ | `aget_state_history` | `Iterator[StateSnapshot]` |
| update_state | ✅ | `aupdate_state` | `RunnableConfig` |
| bulk_update_state | ✅ | `abulk_update_state` | `RunnableConfig` |

```python
def get_state(
    self, config: RunnableConfig, *, subgraphs: bool = False
) -> StateSnapshot:

def get_state_history(
    self, config: RunnableConfig, *,
    filter: dict[str, Any] | None = None,
    before: RunnableConfig | None = None,
    limit: int | None = None,
) -> Iterator[StateSnapshot]:

def update_state(
    self, config: RunnableConfig,
    values: dict[str, Any] | Any | None,
    as_node: str | None = None,
) -> RunnableConfig:

def bulk_update_state(
    self, config: RunnableConfig,
    updates: Sequence[Sequence[StateUpdate]],
) -> RunnableConfig:
```

### 图结构类

| 方法 | 同步 | 异步 | 返回类型 |
|------|------|------|----------|
| get_graph | ✅ | `aget_graph` | `DrawableGraph` |
| with_config | ✅ | — | `Self` |

```python
def get_graph(
    self, config: RunnableConfig | None = None, *,
    xray: int | bool = False,         # 是否展开子图
) -> DrawableGraph:
```

## v1.1 新功能

> ⚠️ 以下功能基于 changelog 已知版本标注；未标注版本号的功能通过 site-packages 源码确认存在，但首次出现版本不确定。

| 功能 | 说明 | 首次版本 |
|------|------|---------|
| `version="v2"` | invoke/stream 返回 `StreamPart`/`GraphOutput`，含 `.value` + `.interrupts` 属性 | v1.1.0 ✅ |
| `subgraphs` | stream 中启用子图事件 | v1.1.0 ✅ |
| `context` 参数 | invoke/stream 中传递上下文（为远程图 API 新增） | v1.1.2 ✅ |
| `bulk_update_state` | 批量更新多个配置的状态 | [不确定版本] |
| `durability` | 检查点耐久性: `"sync"` / `"async"` / `"exit"` | [不确定版本] |

## 类型定义速查

```python
StateSnapshot:       TypedDict(values, next, config, parent_config, metadata, created_at)
StreamMode:          Literal["values", "updates", "checkpoints", "tasks", "debug", "messages", "custom"]
All:                 Literal["*"]
Durability:          Literal["sync", "async", "exit"]  # [不确定版本]
Command:             TypedDict(goto: str | Sequence[str] | None, update: dict | None)  # 中断恢复：指定跳转节点和/或状态更新
StateUpdate:         TypedDict(values, as_node)         # bulk_update_state 用
```

## 使用模式

```python
# 基础调用（无 checkpointer 时可省略 config）
result = graph.invoke({"question": "what is RAG?"})

# 带 checkpointer（必须传 config 含 thread_id）
result = graph.invoke({"question": "what is RAG?"}, {"configurable": {"thread_id": "1"}})

# 流式输出
for chunk in graph.stream({"question": "what is RAG?"}, stream_mode="updates"):
    print(chunk)

# v2 模式（可获取中断信息）
result = graph.invoke(input, version="v2")
if result.interrupts:
    ...
value = result.value

# 状态检查
snapshot = graph.get_state(config)
history = list(graph.get_state_history(config, limit=5))
```
