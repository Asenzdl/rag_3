# LangGraph 配置体系三层架构

> 基于官方文档（oss/python/langgraph/graph-api.mdx, use-graph-api.mdx, concepts/context.mdx）整理
> 验证日期：2026-05-13

---

## 一、总览：三条互不重叠的通道

LangGraph 应用中有三种配置，按生命周期和职责严格分层：

```
进程级 ─────────────────────────────────────────────────────
  Pydantic Settings: API Key, DB 路径, 模型名
  生命周期: 进程启动时加载，运行期间不变

图编译级 ────────────────────────────────────────────────────
  依赖注入: LLM 实例, retriever 实例, citation_extractor
  生命周期: 图编译时绑定，编译后不变

invoke 级 ─┬── context_schema → Runtime.context ── 应用运行时配置
           │    生命周期: 每次 invoke 独立传入
           │
           └── RunnableConfig ── LangGraph 框架配置
                生命周期: 每次 invoke 独立传入
```

三层互不替换，各有标准职责。

---

## 二、节点函数参数注入机制（官方签名）

官方文档（graph-api.mdx Nodes 章节）定义节点可接收三个参数：

```python
def my_node(
    state: State,                          # 图状态（必有）
    config: RunnableConfig,                # 框架级配置（可选）
    runtime: Runtime[ContextSchema],       # 运行时上下文（可选）
) -> dict:
    ...
```

LangGraph 通过**参数名 + 类型注解**自动注入：

| 参数名 | 类型 | 注入条件 | 内容 |
|--------|------|---------|------|
| `state` | 你的 State 类型 | 第一个参数，必有 | 图状态（所有节点间传递的数据） |
| `config` | `RunnableConfig` | 参数名匹配 | thread_id, tags, tracing, recursion_limit |
| `runtime` | `Runtime[Ctx]` | 参数名匹配 | `runtime.context`, `runtime.store`, `runtime.stream_writer` |

三种签名可以任意组合：
```python
def node_a(state: State) -> dict:                              # 只读 state
def node_b(state: State, config: RunnableConfig) -> dict:      # state + 框架配置
def node_c(state: State, runtime: Runtime[Ctx]) -> dict:       # state + 应用配置
def node_d(state: State, config: RunnableConfig, runtime: Runtime[Ctx]) -> dict:  # 全部
```

---

## 三、第 1 层：Pydantic Settings（进程级）

### 职责范围

官方对 Pydantic Settings 没有专门章节，但在 context_schema 文档中用对比表明确了分工。

**放在 Settings 中的典型字段**：
- API Key（`deepseek_api_key`, `qwen_api_key`）
- Base URL（`deepseek_base_url`, `ollama_base_url`）
- 向量库路径（`chroma_persist_directory`）
- 模型名（`embedding_model`, `llm_provider`）
- 检查点数据库路径（`checkpoint_db_path`）

**为什么这些不进 LangGraph**：
- 生命周期是进程级（启动时确定，运行中不变）
- LangGraph 的 context 和 config 都是 invoke 级（每次调用可不同）
- 用 invoke 级通道传不变的值是浪费，且把"配置从哪里来"和"配置传到哪里"混为一谈

### 与 LangGraph 的衔接方式

Settings 不直接进入 LangGraph，而是通过**工厂函数**创建依赖后注入：

```python
# 正确方式：Settings → 工厂 → 依赖 → 图
settings = Settings()
llm = create_llm(settings.llm_provider, settings)
retriever = create_retriever(settings)
graph = build_graph(retriever=retriever, llm=llm)
```

---

## 四、第 2 层：context_schema / Runtime.context（invoke 级，应用配置）

### 官方定位

> "Sometimes you want to be able to configure your graph when calling it. For example, you might want to be able to specify what LLM or system prompt to use at runtime, **without polluting the graph state with these parameters**." — use-graph-api.mdx, "Add runtime configuration"

> "Runtime context is a form of dependency injection and can be used to optimize the LLM context. It lets you provide dependencies (like database connections, user IDs, or API clients) to your tools and nodes at runtime rather than hardcoding them." — concepts/context.mdx

### 官方示例 1：运行时选择 LLM

```python
from dataclasses import dataclass
from langchain.chat_models import init_chat_model
from langgraph.graph import MessagesState, END, StateGraph, START
from langgraph.runtime import Runtime

@dataclass
class ContextSchema:
    model_provider: str = "anthropic"

MODELS = {
    "anthropic": init_chat_model("claude-haiku-4-5-20251001"),
    "openai": init_chat_model("gpt-5.4-mini"),
}

def call_model(state: MessagesState, runtime: Runtime[ContextSchema]):
    model = MODELS[runtime.context.model_provider]
    response = model.invoke(state["messages"])
    return {"messages": [response]}

builder = StateGraph(MessagesState, context_schema=ContextSchema)
builder.add_node("model", call_model)
builder.add_edge(START, "model")
builder.add_edge("model", END)
graph = builder.compile()

# 调用时传 context（不传则用 dataclass 默认值）
response = graph.invoke(
    {"messages": [{"role": "user", "content": "hi"}]},
    context=ContextSchema(),                         # 默认 anthropic
)
response = graph.invoke(
    {"messages": [{"role": "user", "content": "hi"}]},
    context={"model_provider": "openai"},             # dict 也支持
)
```

### 官方示例 2：运行时配置 system message

```python
@dataclass
class ContextSchema:
    model_provider: str = "anthropic"
    system_message: str = ""

def call_model(state: MessagesState, runtime: Runtime[ContextSchema]):
    system_message = runtime.context.system_message
    messages = ([SystemMessage(content=system_message)] if system_message else [])
    messages += state["messages"]
    model = MODELS[runtime.context.model_provider]
    response = model.invoke(messages)
    return {"messages": [response]}

graph.invoke(
    {"messages": [{"role": "user", "content": "hi"}]},
    context={"model_provider": "openai", "system_message": "Respond in Italian."},
)
```

### 官方示例 3：带 store 的跨会话记忆

```python
from langgraph.store.base import BaseStore

@dataclass
class Context:
    user_id: str

async def call_model(
    state: MessagesState,
    runtime: Runtime[Context],
):
    # context 中的 user_id 用于 store 寻址
    namespace = ("memories", runtime.context.user_id)
    memories = await runtime.store.asearch(namespace)
    # ... 使用 memories 增强 prompt
```

### 关键行为

| 行为 | 说明 |
|------|------|
| context_schema 定义后 context 参数仍是可选的 | `runtime.context` 可能为 `None` |
| dataclass 默认值只在传 `context=MyCtx()` 时生效 | 不传 context 时 `runtime.context` 是 None |
| context 不被 checkpointer 持久化 | 每次 invoke 独立上下文，不序列化到数据库 |
| 一个图只能有一个 context_schema | 所有运行时配置定义在一个类型中 |
| TypedDict 和 dataclass 均可 | dataclass 支持默认值，TypedDict 需 `total=False` |

---

## 五、第 3 层：RunnableConfig（invoke 级，框架配置）

### 官方定位

> "config — A RunnableConfig object that contains **configuration information like `thread_id` and tracing information like `tags`**" — graph-api.mdx, Nodes 章节

### 标准字段

| 字段 | 位置 | 用途 |
|------|------|------|
| `thread_id` | `config["configurable"]["thread_id"]` | checkpointer 会话标识 |
| `recursion_limit` | `config["recursion_limit"]` | 超步数硬限制（独立键！） |
| `tags` | `config["tags"]` | 追踪/调试标签 |
| `metadata` | `config["metadata"]` | 自定义元数据 |
| `max_concurrency` | `config["configurable"]["max_concurrency"]` | 并行节点最大并发数 |

官方特别说明（graph-api.mdx "Recursion limit" 章节）：

> "recursion_limit is a **standalone config key** and should not be passed inside the configurable key as all other user-defined configuration."

翻译：`recursion_limit` 是独立键（在 config 顶层而非 configurable 内）。**`configurable` 本身是为框架级参数预留的命名空间，不是给业务配置的。**

### 节点中读取 config

```python
from langchain_core.runnables import RunnableConfig

def my_node(state: State, config: RunnableConfig) -> dict:
    thread_id = config["configurable"]["thread_id"]
    current_step = config["metadata"]["langgraph_step"]
    return state
```

### config 的正确用途 vs 常见误用

| ✅ 正确（框架控制） | ❌ 错误（应走 context_schema） |
|---|---|
| `thread_id: "session-abc"` | `max_iterations: 3` |
| `recursion_limit: 50` | `memory_max_tokens: 4000` |
| `tags: ["prod"]` | `model_provider: "deepseek"` |
| `max_concurrency: 10` | `user_id: "alice"` |

---

## 六、决策矩阵

给定一个配置值，按以下顺序判断放哪：

```
这个值是进程启动时就确定的吗？
  ├─ 是（API Key、DB 路径、模型名）
  │   └→ Pydantic Settings（进程级）
  │
  └─ 否（每次 invoke 可能不同）
      ├─ 这个值是给 LangGraph 框架读的吗？
      │   ├─ 是（thread_id、recursion_limit）
      │   │   └→ RunnableConfig（invoke 级，框架）
      │   │
      │   └─ 否（你的业务节点要读的值）
      │       └→ context_schema → Runtime.context（invoke 级，应用）
      │
      └─ 这个值是 LLM 实例、retriever 实例这类服务对象吗？
          └→ 依赖注入（图编译时传入）
```

### 项目当前 Settings 评估结果

| Settings 字段 | 当前归属 | 建议归宿 |
|--------------|---------|---------|
| deepseek_api_key | Settings | 留 Settings（进程级） |
| qwen_api_key | Settings | 留 Settings（进程级） |
| deepseek_base_url | Settings | 留 Settings（进程级） |
| ollama_base_url | Settings | 留 Settings（进程级） |
| vectorstore_type | Settings | 留 Settings（进程级） |
| chroma_persist_directory | Settings | 留 Settings（进程级） |
| embedding_model | Settings | 留 Settings（进程级） |
| llm_provider | Settings | 留 Settings（进程级） |
| checkpoint_db_path | Settings | 留 Settings（进程级） |
| **max_iterations** | **Settings → 工厂参数** | **→ context_schema（invoke 级）** |
| eval_qa_path / eval_report_path | Settings | 留 Settings（离线工具，不涉及图） |

### invoke 时三参数同时传入

```python
graph.invoke(
    inputs,                                           # 图输入（state）
    config={"configurable": {"thread_id": "s1"}},     # 框架级
    context=GraphContext(max_iterations=3),            # 应用级
)
```

---

## 七、常见误区澄清

### 误区 1："`config.configurable` 可以放业务配置"

官方文档中 `configurable` 的用例全是框架参数（thread_id, max_concurrency）。官方示例中业务运行时配置全部使用 `context` 参数。`configurable` 是框架命名空间，你的业务代码不应与框架参数混放。

### 误区 2："LLM 实例可以放 context 或 config"

LLM 实例（`BaseChatModel` 对象）不可序列化，而 context 和 config 都可能被 LangGraph 内部传递/序列化。正确做法是：`context` 中放**模型选择标识**（如 `model_provider: str`），节点内部通过标识从注册表获取实例。

### 误区 3："Settings 应该被重构掉"

Pydantic Settings 是进程级配置的标准方案，LangGraph 没有替代它。正确的重构方向是：**不要让图构建函数直接依赖 Settings**（即 `build_graph(settings)` → `build_graph(retriever, llm)`），而不是把 Settings 的字段迁移到 LangGraph 的配置通道中。

---

## 参考链接

- [Graph API 文档（Nodes 章节）](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Use Graph API（Add runtime configuration 章节）](https://docs.langchain.com/oss/python/langgraph/use-graph-api)
- [Context Overview 文档](https://docs.langchain.com/oss/python/concepts/context)
- [Runtime 对象文档](https://docs.langchain.com/oss/python/langchain/runtime)
