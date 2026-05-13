## Task 2.4c context_schema 运行时配置注入

### 任务目标

消除 Workflow 路径中 `max_iterations` 作为工厂参数传入 `create_workflow_nodes` 的生命周期错配，改为通过 LangGraph `context_schema` 机制在 invoke 时注入。为 Task 2.5（记忆管理）复用同一通道新增运行时参数铺平管道。

**设计约束**（此 Task 产出的决策与 Task 2.5/2.6 共同生效）：
- 第 0 层（用户画像）：学习 LangGraph 官方三层配置架构（Settings / context_schema / RunnableConfig）的职责边界
- 第 1 层（质量准则 1/3/4）：模块分离避免工厂参数混杂，依赖倒置避免硬编码，封装隐藏 Runtime 注入细节
- 第 2 层（Task 指令）：现有 `max_iterations` 工厂参数 → `GraphContext` 字段；仅 generate_node 加 runtime 参数，不超前注入未消费的节点
- 第 3 层（前瞻性边界）：不做多余抽象，只迁移当前已有的一个运行时参数，不预实现 Task 2.5 的字段

### 实施方案

1. `src/workflow/state.py` 新增 `GraphContext` dataclass，包含 `max_iterations: int = 3` 一个字段。与 `GraphState` 同文件管理图相关类型，不单独建文件。
2. `src/workflow/nodes.py` 中 `create_workflow_nodes` 移除 `max_iterations` 参数，同时删除 logger 对 `max_iterations` 的引用（第 96 行）；修正返回类型 `Callable[[GraphState], dict]` 为 `Callable[..., dict]`；`generate_node` 签名增加 `runtime: Runtime[GraphContext]`，内部通过 `runtime.context.max_iterations if runtime.context is not None else 3` 读取。
3. `src/workflow/builder.py` 中 `StateGraph(GraphState)` 改为 `StateGraph(GraphState, context_schema=GraphContext)`；`create_workflow_nodes` 调用不再传 `max_iterations=settings.max_iterations`。
4. `settings.py` 保留 `max_iterations` 字段——语义变更为"构建默认 GraphContext 的配置源"。调用方（当前为测试文件，Task 2.7 起为 CLI 入口）在 invoke 时负责构造 `GraphContext(max_iterations=settings.max_iterations)` 传入。builder 本身只注册 schema 类型，不持有默认实例。
5. 测试适配：generate_node 的测试调用方需传入 `Runtime(context=GraphContext(max_iterations=3))`，builder 端到端测试无需改动（invoke 不传 context 时节点使用硬编码兜底值）。

### 涉及文件

**修改文件（workflow 路径）：**
- `src/workflow/state.py` — 新增 `GraphContext` dataclass + 加入 `__all__`
- `src/workflow/nodes.py` — 移除 `max_iterations` 参数及第 96 行对应 logger 引用；修正返回类型为 `Callable[..., dict]`；generate_node 签名增加 `runtime`；新增 import `from langgraph.runtime import Runtime`
- `src/workflow/builder.py` — StateGraph 注册 `context_schema=GraphContext`；停止向 `create_workflow_nodes` 传 `max_iterations`
- `src/workflow/__init__.py` — 新增 `GraphContext` 导出

**测试文件：**
- `tests/test_workflow_nodes.py` — generate_node 测试用例增加 `Runtime(context=GraphContext())` fixture

**未修改文件：**
- `src/core/settings.py` — `max_iterations` 保留作为默认值源
- `src/workflow/edges.py` — 条件边路由函数不感知 context
- `src/workflow/routing.py` — 意图分类逻辑不变
- `src/workflow/prompts.py` — 模板管理不变
- `src/workflow/citation.py` — 引用提取不变
- `src/workflow/checkpointer.py` — 检查点管理不变
- `src/app.py` — 使用 RAGChain，不涉及 Workflow
- `src/generation/` 全部 — 完全不碰

### 架构决策记录

#### 决策 1：`GraphContext` 放 `state.py` 而非独立文件

**问题**：`GraphContext` 是新的类型定义，应放在单独 `context.py` 还是与 `GraphState` 同文件？

**候选方案**：
- A（合并到 state.py）：`GraphState` + `GraphContext` 都在 `src/workflow/state.py`
- B（独立文件）：新建 `src/workflow/context.py`

**选择 A**，理由：
- `GraphContext` 是 Schema 定义，与 `GraphState` 同属"状态/配置类型"的关注点
- 一个 dataclass（一个字段）不值得一个文件——单独文件增加导航成本
- 所有图相关类型集中在一个文件，导入路径统一为 `from .state import GraphState, GraphContext`

#### 决策 2：仅 generate_node 加 runtime 参数

**问题**：`route_node` 和 `retrieve_node` 是否需要同时更新签名以保持一致？

**候选方案**：
- A（最小改动）：只给 generate_node 加 `runtime`，route/retrieve 不变
- B（统一签名）：所有节点加 `runtime` 保持一致性

**选择 A**，理由：
- 当前只有 generate_node 消费 `max_iterations`（虽然只存不用，Task 2.6 才做条件边检查）
- LangGraph 不要求所有节点签名一致——只需要每个节点的签名被框架正确匹配
- 不超前注入未消费的参数，符合最小接口原则

#### 决策 3：settings.max_iterations 保留作为默认值源

**问题**：`max_iterations` 进 `context_schema` 后，settings 中的同名字段是否删除？

**候选方案**：
- A（保留）：settings 保留 `max_iterations`，调用方在 invoke 时构造 `GraphContext(max_iterations=settings.max_iterations)` 传入
- B（删除）：settings 不再含此字段，调用方硬编码默认值 `3`

**选择 A**，理由：
- 配置集中管理的原则不变——settings 仍是所有配置的唯一来源
- 调用方不传 `context` 时代码退化到当前行为（`runtime.context` 为 None → 硬编码兜底 3），但 builder 提供的默认实例覆盖率优于全局硬编码
- 删除它会导致硬编码数字 3，降低可配置性

#### 决策 4：`runtime.context` 为 None 时使用硬编码兜底

**问题**：`runtime.context` 可能为 None（调用方不传 context 时），应如何处理？

**候选方案**：
- A（assert 立即失败）：`assert runtime.context is not None, "context 必需"`
- B（静默兜底）：`if runtime.context is None: max_iterations = 3`

**选择 B**，理由：
- `context_schema` 定义后 invoke 不传 context 仍是合法操作
- assert 导致调用方必须传 context，违反可选语义
- 静默兜底 + logger.warning 记录无 context 情况，既防御又可观测

### 面试级知识点

- **LangGraph 三层配置架构**：Pydantic Settings（进程级）→ context_schema / Runtime.context（invoke 级应用配置）→ RunnableConfig（invoke 级框架配置）。三层生命周期和职责不重叠。
- **Runtime 注入机制**：LangGraph 通过参数名 `runtime` + 类型注解 `Runtime[Ctx]` 自动注入运行时上下文。节点不需要手动创建或传递 Runtime 实例。
- **context 不被 checkpointer 持久化**：context 是每次 invoke 独立传入的，不序列化到检查点数据库。这与 state 不同——state 由 checkpointer 自动保存。
- **context_schema vs config_schema**：`context_schema` 自 v0.6.0 起取代已弃用的 `config_schema`。v1.0+ 中 `config_schema` 发出 DeprecationWarning。
- **context_schema 与 Store 的关系**：`Runtime` 对象还携带 `store` 字段（`BaseStore` 实例）。引入 context_schema 后，`Runtime` 已在节点签名中，未来引入跨会话记忆时 `runtime.store` 直接可用，无需再次修改签名。

### 生产级注意事项

- **`runtime.context` 的 null 安全**：即使 `context_schema` 已定义且 dataclass 有默认值，不传 `context` 时 `runtime.context is None`。dataclass 默认值只在 `context=GraphContext()` 时生效。
- **context 参数可覆盖性**：invoke 时可独立覆盖——`graph.invoke(inputs, context=GraphContext(max_iterations=10))` 覆盖默认值，调试和生产可用不同阈值。
- **`create_workflow_nodes` 签名净化**：迁移后此函数只保留服务依赖（retriever、llm、citation_extractor），所有运行时配置走 `GraphContext`。Task 2.5 新增参数时无需修改工厂签名。
- **`build_graph` 的调用方契约**：返回的 `CompiledStateGraph` 现在注册了 `context_schema`，建议调用方在 invoke 时传入 `context` 参数。docstring 注明建议用法。
- **`context_schema` 仅支持一个类型**：一个图只能有一个 `context_schema`，所有运行时配置字段定义在同一个 `GraphContext` 类中，不可拆分为多个 schema 分别注入。

### 验收标准

- `src/workflow/state.py` 新增 `GraphContext` dataclass，字段 `max_iterations: int = 3`，加入 `__all__`。
- `create_workflow_nodes` 签名不再含有 `max_iterations` 参数，已删除相关 logger 行（第 96 行），返回类型标注修正为 `Callable[..., dict]`。
- `generate_node` 内部通过 `runtime.context.max_iterations` 读取最大迭代次数，null-safe 兜底值为 3。
- `build_graph` 中 `StateGraph` 注册 `context_schema=GraphContext`。
- `src/workflow/__init__.py` 导出 `GraphContext`。
- `settings.py` 中 `max_iterations` 保留，workflow 路径无直接引用——调用方在 invoke 时通过 `GraphContext(max_iterations=settings.max_iterations)` 使用。
- 所有已有测试通过（`test_workflow_nodes.py`、`test_workflow_builder.py`）。
