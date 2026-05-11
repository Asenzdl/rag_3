# LangGraph v2 Streaming API 参考

> 版本：langgraph 1.1.10 | 来源：context7 查询 + site-packages 源码确认
> 用途：`version="v2"` 模式下的 invoke/stream API 变更速查
> **信任此文档**

---

## v1 → v2 核心差异

### v1 的问题

v1 的 `stream()` 返回值**格式随 stream_mode 组合变化**，调用方无法统一处理：

| stream_mode | v1 返回值类型 | 问题 |
|---|---|---|
| `"updates"` | 裸 dict `{node: {k: v}}` | 无 `type` 标识，不知道是什么事件 |
| `"values"` | 裸 dict `{k: v}` | 同上 |
| `["values", "updates"]` | **tuple** `(dict, dict)` | 多种模式的 chunk 格式和单模式完全不同 |
| 其他组合 | 不固定 | 调用方需要针对每种组合写不同解析逻辑 |

这导致 FastAPI SSE 等场景中，服务端代码必须感知客户端请求了哪种 stream_mode，否则无法正确解析。

### v2 解决方式

v2 统一了所有模式、所有组合的输出格式：

| | v1（默认） | v2 |
|---|---|---|
| `invoke()` 返回 | 原始 dict | `GraphOutput` 对象（`.value` + `.interrupts`） |
| `stream()` 产出 | 格式随 mode 变化 | 统一 `{type, ns, data}` StreamPart |
| 多种 stream_mode | 格式不一致 | 同一种结构，`type` 字段区分 |
| Pydantic 输出 | 需手动解析 | 自动 coercion |
| Subgraph 流式 | 需要额外配置 | 仍需 subgraphs=True |

**关键**：不传 `version="v2"` 时 v1 行为完全不变。v2 是 opt-in，现有代码不受影响。

---

## invoke(version="v2")

```python
result: GraphOutput = graph.invoke(input, version="v2")
# result.value      → OutputT  状态字典或 Pydantic 模型（见 Pydantic Coercion）
# result.interrupts → tuple[Interrupt, ...]  中断信息
```

**GraphOutput 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `value` | `OutputT` | 图执行结果（同 v1 的 dict 返回值） |
| `interrupts` | `tuple[Interrupt, ...]` | 执行期间发生的所有中断 |

**Interrupt 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `value` | `Any` | 中断值（`NodeInterrupt` 时携带的信息） |
| `id` | `str` | 中断 ID，可用于恢复中断 |

**典型用法：**
```python
result = graph.invoke({"question": "什么是 RAG?"}, version="v2")
if result.interrupts:
    for interrupt in result.interrupts:
        print(f"中断: {interrupt}")
answer = result.value  # 正常取结果
```

---

## stream(version="v2")

```python
for event in graph.stream(input, version="v2", stream_mode="values"):
    # event 是 StreamPart 子类的实例
    print(event.type, event.ns, event.data)
```

> StreamPart 类型定义在 `langgraph.types` 中（如 `ValuesStreamPart`、`UpdatesStreamPart` 等）

### stream_mode 可选值

| 模式 | 对应 StreamPart 类型 | data 内容 |
|------|---------------------|-----------|
| `"values"` | `ValuesStreamPart` | 完整状态 `OutputT` |
| `"updates"` | `UpdatesStreamPart` | 节点增量 `dict[str, Any]` |
| `"messages"` | `MessagesStreamPart` | 消息对 `tuple[AnyMessage, dict[str, Any]]` |
| `"custom"` | `CustomStreamPart` | 自定义数据 `Any` |
| `"tasks"` | `TasksStreamPart` | 任务负载 `TaskPayload | TaskResultPayload` |
| `"debug"` | `DebugStreamPart` | 调试负载 `DebugPayload[StateT]` |
| `"checkpoints"` | `CheckpointStreamPart` | 检查点负载 `CheckpointPayload[StateT]` |

### StreamPart 公共字段

所有 StreamPart 共有的三个字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `Literal["values", "updates", "messages", "custom", "tasks", "debug", "checkpoints"]` | 对应 stream_mode 的字符串标识 |
| `ns` | `tuple[str, ...]` | 节点命名空间路径（子图用，如 `("agent", "tools")`） |
| `data` | 取决于类型 | 事件负载数据 |

### 典型用法

```python
# values 模式：获取每一步的完整状态
for event in graph.stream(input, version="v2", stream_mode="values"):
    if event.type == "values":
        state = event.data  # 当前完整状态 dict
        if "messages" in state:
            print(state["messages"][-1].content)

# updates 模式：获取节点增量
for event in graph.stream(input, version="v2", stream_mode="updates"):
    if event.type == "updates":
        for node_name, update in event.data.items():
            print(f"节点 {node_name} 产出: {update}")

# messages 模式：逐条消息
for event in graph.stream(input, version="v2", stream_mode="messages"):
    if event.type == "messages":
        msg, metadata = event.data
        print(f"[{msg.type}] {msg.content[:50]}")
```

---

## Pydantic / Dataclass Coercion（v2 自动转换）

v2 模式下，如果声明了输出类型，`invoke()` 自动将 dict 转换为目标类型：

```python
from pydantic import BaseModel

class QAOutput(BaseModel):
    question: str
    answer: str

# 假设图返回 {"question": "...", "answer": "..."}
result = graph.invoke(input, version="v2")
# result.value 自动是 QAOutput 实例（而非 dict）
print(result.value.answer)
```

无需手动 `QAOutput(**dict)` 转换。

---

## 使用建议

| 场景 | 推荐模式 | 原因 |
|------|---------|------|
| 取最终结果 + 检查中断 | `invoke(version="v2")` | `GraphOutput.interrupts` 直接可用 |
| 逐节点观察执行过程 | `stream(version="v2", stream_mode="updates")` | 知道每个节点产出什么 |
| 流式输出 LLM token | `stream(version="v2", stream_mode="messages")` | 逐条消息推送 |
| 实时状态刷新（UI） | `stream(version="v2", stream_mode="values")` | 每次状态变更都有完整快照 |
