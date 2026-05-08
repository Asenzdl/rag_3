# Task 2.4 检查点持久化（Checkpointer） - 架构设计

> **原始需求**：`.project/outline/phase_2_langgraph/task_2.4_checkpointer.md`
> **涉及文件**：`src/workflow/checkpointer.py`、`src/workflow/builder.py`（修改）、`src/workflow/__init__.py`（更新导出）、`tests/test_workflow_checkpointer.py`

---

## 架构决策与权衡

### 先读：这不是"加一行 checkpointer 参数"的事

把 `checkpointer` 传入 `graph.compile()` 看似一行代码的事，但 **checkpointer 的生命周期管理模式**决定了 app.py 是继续保持简单初始化还是必须重构为上下文管理器，**build_graph 的签名变更**决定了测试是否能在无 checkpointer 场景下独立运行，**返回类型的抽象层级**决定了切换 PostgresSaver 时的影响范围——选错任何一项，要么资源泄漏，要么测试瘫痪，要么后续扩展时大面积改签名。

---

### 入口判定

1. **checkpointer.py 的生命周期管理模式**：`SqliteSaver.from_conn_string()` 是 `@contextmanager`——调用方必须用 `with` 语句。如果我们绕过它直接创建连接，代码结构完全不同（无需 `with`，但失去自动清理）。**命中**。

2. **build_graph 签名与 checkpointer 集成**：checkpointer 是 build_graph 内部创建（Settings 驱动）还是外部传入（依赖注入）？换方案会改变 build_graph 的职责边界和测试方式。**命中**。

3. **create_checkpointer 的返回类型**：返回具体 `SqliteSaver` vs 抽象 `BaseCheckpointSaver`？不改变代码结构（`graph.compile()` 两者都接受），仅影响类型注解和未来扩展时的影响范围。**不命中**——归入非关键决策。

---

### 决策 1：checkpointer.py 生命周期管理模式 — 上下文管理器包装 from_conn_string

**语境**：`SqliteSaver.from_conn_string()` 返回 `Iterator[SqliteSaver]`（`@contextmanager` 装饰），在 `with` 块退出时自动关闭 sqlite3 连接。验收标准明确要求"使用 `SqliteSaver.from_conn_string("db/checkpoints.db")` 创建检查点"。这意味着我们必须用 `from_conn_string`，而非直接 `sqlite3.connect()` + `SqliteSaver(conn)`。

**候选对比**：

- **方案 A**：`create_checkpointer(settings)` 为 `@contextmanager`，内部调用 `from_conn_string`
  - 优势：使用 `from_conn_string` 满足验收标准；连接自动关闭（无资源泄漏）；遵循 LangGraph 官方模式
  - 硬伤：调用方必须用 `with` 语句，改变了 app.py 的初始化结构

- **方案 B**：`create_checkpointer(settings)` 直接创建 `sqlite3.connect()` + `SqliteSaver(conn)`
  - 优势：调用方无需 `with` 语句，集成更简单；长生命周期对象直接返回
  - 硬伤：不使用 `from_conn_string`（违反验收标准）；连接需手动关闭（资源泄漏风险）；绕过 LangGraph 的连接管理模式（`check_same_thread=False` 等细节需自行处理）

**反驳推演**：如果选方案 B，虽然集成更简单，但 (1) 验收标准明确要求 `from_conn_string`，(2) 我们需要自行处理 `check_same_thread=False`、连接关闭等 `from_conn_string` 已封装的逻辑，(3) 长期看，`from_conn_string` 的上下文管理器模式是 LangGraph 的标准用法，绕过它意味着维护一份自建的连接管理代码。

**结论**：选 A。`create_checkpointer` 为 `@contextmanager`，内部调用 `from_conn_string` + `setup()`，yield 配置好的检查点管理器。调用方（app.py）用 `with` 语句管理生命周期。这是验收标准的要求，也是资源安全的保障。如果 LangGraph 未来提供非上下文管理器的创建方式，结论会反转。

**反事实自检**：

- [x] 方案 B 不再失效（如果验收标准不要求 `from_conn_string`），两方案都可行 → "验收标准要求使用 from_conn_string"正是让方案 B 失效的原因 → 验证通过

---

### 决策 2：build_graph 签名 — 可选 checkpointer 参数（外部传入）

**语境**：Task 2.3 的 `build_graph(settings)` 内部通过 factories 创建所有依赖（retriever、llm、prompt），checkpointer 是新引入的依赖。checkpointer 的创建涉及资源管理（数据库连接），与 retriever/llm 的"创建即用"模式不同。

**候选对比**：

- **方案 A**：`build_graph(settings, checkpointer=None)` — checkpointer 由外部创建并传入
  - 优势：build_graph 不承担 checkpointer 生命周期管理（SRP）；测试可在无 checkpointer 场景下运行；与 Task 2.3 设计文档预期一致
  - 硬伤：调用方需要自行创建 checkpointer（但这正是生命周期管理的正确归属）

- **方案 B**：`build_graph(settings)` — 内部读取 settings 创建 checkpointer
  - 优势：调用方无感知，一行调用即可
  - 硬伤：build_graph 需要管理数据库连接生命周期（何时关闭？）；测试无法在无 checkpointer 场景下运行（或需要 mock Settings 中的 checkpoint_db_path）；违反 SRP（图构建 ≠ 资源管理）

- **方案 C**：`build_graph(settings, use_checkpointer=False)` — 内部创建但可选
  - 优势：兼顾简单性和可选性
  - 硬伤：内部创建意味着内部管理生命周期——但 build_graph 返回的 CompiledGraph 可能比连接活得更久，连接何时关闭？这需要 build_graph 变成上下文管理器，改变现有 API 的根本形态

**反驳推演**：如果选方案 B，build_graph 既负责"组装图"又负责"管理数据库连接"，两个职责的生命周期不同步：CompiledGraph 可被缓存和复用，但数据库连接需要在应用退出时关闭。这种不匹配导致要么连接泄漏（不关闭），要么图失效（连接关闭后图不可用）。方案 A 将生命周期管理交给调用方，调用方自然控制两者的生命周期同步。

**结论**：选 A。`build_graph(settings, checkpointer=None)` 接受可选的 checkpointer 参数。checkpointer 的创建和生命周期由调用方管理。这是依赖注入的标准实践，也符合 Task 2.3 设计文档的预期（"build_graph 将需要接受 checkpointer 参数"）。如果 build_graph 不需要测试且应用生命周期等同于连接生命周期，结论可能反转——但这两者都不成立。

**反事实自检**：

- [x] 方案 B 不再失效（如果 build_graph 不需要测试且图的生命周期与连接完全同步），两方案都可行 → "build_graph 需要在无 checkpointer 场景下测试"正是让方案 B 的内部创建失效的原因 → 验证通过

---

### 非关键决策

#### 决策 1：create_checkpointer 的返回类型注解 — BaseCheckpointSaver

- **选项 A**：返回类型注解为 `SqliteSaver` — 精确但依赖具体实现
- **选项 B**：返回类型注解为 `BaseCheckpointSaver` — 抽象，符合 DIP
- **结论**：选 B。生产级注意事项要求"预留 PostgreSQL 可扩展接口"，返回抽象类型使得未来切换 PostgresSaver 时调用方签名不变。`setup()` 在内部调用后 yield，调用方只使用 `BaseCheckpointSaver` 的方法（`get`/`put`/`list` 等），不依赖 `SqliteSaver` 特有方法。

#### 决策 2：数据库目录自动创建

- **选项 A**：`create_checkpointer` 内部确保目录存在
- **选项 B**：假定目录已存在（依赖部署约定）
- **结论**：选 A。`sqlite3.connect` 不会创建父目录，目录不存在时抛出 `FileNotFoundError`。自动创建是防御性编程——避免因部署环境差异导致的启动失败。成本仅一行 `os.makedirs(exist_ok=True)`。

#### 决策 3：create_checkpointer 接受 Settings 而非 conn_string

- 与项目中所有工厂函数保持一致（`create_retriever(settings)`、`create_llm(provider, settings)`）
- Settings 是配置的唯一来源，避免在 checkpointer.py 中硬编码路径

#### 决策 4：checkpointer 参数在 build_graph 中的类型注解

- 使用 `BaseCheckpointSaver | None` 而非 `SqliteSaver | None`——与决策 1 一致，build_graph 不依赖具体 checkpointer 实现

---

### 质量准则豁免

无需豁免。10 维准则在本 Task 中均有体现。

---

## 模块结构

### 文件组织
```
src/workflow/
├── __init__.py          # 更新：导出 create_checkpointer
├── state.py             # 不变
├── routing.py           # 不变
├── nodes.py             # 不变
├── edges.py             # 不变
├── checkpointer.py      # 新增：检查点持久化工厂
└── builder.py           # 修改：build_graph 签名变更
```

### 关键外部依赖（仅列非标准库）
```
checkpointer.py
├── langgraph.checkpoint.sqlite    # SqliteSaver
├── langgraph.checkpoint.base      # BaseCheckpointSaver
└── src.core.settings              # Settings

builder.py（新增依赖）
└── langgraph.checkpoint.base      # BaseCheckpointSaver（类型注解）
```

### 职责边界
```
checkpointer.py 职责：
✅ 包含：create_checkpointer(settings) 工厂函数（上下文管理器模式）
✅ 包含：数据库目录自动创建逻辑
✅ 包含：setup() 调用（数据库表初始化）
❌ 不包含：图构建逻辑 ← 属于 builder.py
❌ 不包含：thread_id 管理 ← 属于调用方（app.py / 测试）
❌ 不包含：检查点清理策略 ← 属于运维配置（Task 2.7+）
  注：SqliteSaver 提供 `prune()` 方法可按数量/时间清理过期检查点，
  但验收标准未要求，当前不接入。Phase 5 服务化时可按需启用。

builder.py 职责变化：
✅ 新增：accept 可选 checkpointer 参数
✅ 新增：将 checkpointer 传递给 graph.compile()
❌ 不包含：checkpointer 创建逻辑 ← 属于 checkpointer.py
```

### 与后续 Task 的接口衔接
- Task 2.5：对话记忆（短期记忆 + 摘要记忆）通过 checkpointer 的状态持久化自动支持——同一 thread_id 的多次 invoke 自动累积 messages
- Task 2.7：CLI 升级需用 `with create_checkpointer(settings)` 包裹应用主循环，并生成/管理 thread_id。具体集成模式：
  ```python
  # app.py (Task 2.7 集成骨架)
  with create_checkpointer(settings) as checkpointer:
      graph = build_graph(settings, checkpointer=checkpointer)
      session = ChatSession()
      cli_loop_with_graph(graph, session)  # REPL 在 with 块内执行
  ```
  `cli_loop` 当前使用 RAGChain，Task 2.7 将改为使用 CompiledGraph + thread_id。
- Phase 5：`create_checkpointer` 可通过 Settings 配置切换为 PostgresSaver（当前返回类型已预留 BaseCheckpointSaver）

---

## 错误处理策略

| 异常/异常场景 | 处理方式 | 中断主流程？ | 理由 |
|------|---------|------------|------|
| 数据库目录不可创建（权限不足） | 传播 OSError，由调用方处理 | 是 | 目录创建失败意味着无法持久化，应快速失败 |
| SqliteSaver.from_conn_string 内部异常 | 传播原始异常，由 `with` 语句确保资源清理 | 是 | 连接创建失败意味着检查点不可用，应用无法启动 |
| setup() 失败（表创建异常） | 传播原始异常 | 是 | 表不存在导致后续所有操作失败，不应静默忽略 |
| checkpointer=None（无持久化） | graph.compile(checkpointer=None)，与之前行为一致 | 否 | 向后兼容，无检查点时不影响图执行 |

---

## 测试策略概要

### 可独立测试的函数/方法

- `create_checkpointer(settings)`：验证上下文管理器 yield 的 checkpointer 可用
- `build_graph(settings, checkpointer=checkpointer)`：验证带 checkpointer 的图编译成功

### Mock 边界

- **Settings**：测试使用真实 Settings 实例，checkpoint_db_path 指向 `:memory:` 或临时文件
- **factories 模块**：测试 build_graph 时 mock `create_retriever`、`create_llm`、`get_prompt`（与 Task 2.3 测试一致）

### 必须覆盖的关键测试场景

1. **create_checkpointer 基础功能**：
   - 返回的 checkpointer 是 BaseCheckpointSaver 实例
   - 数据库目录自动创建
   - setup() 被调用（通过后续 invoke 验证）

2. **build_graph 向后兼容性**：
   - `build_graph(settings, checkpointer=None)` 编译成功
   - 编译后的图可执行（无 thread_id 要求）

3. **多轮对话状态累积**（验收标准核心）：
   - 3 次 invoke 使用相同 thread_id
   - 验证 messages 逐轮累积（Q1 → Q1+A1 → Q1+A1+Q2 → ...）
   - 验证 `graph.get_state(config)` 返回完整状态快照

4. **中断恢复**（验收标准核心）：
   - 使用临时文件创建 checkpointer
   - 第一次 with 块：执行 1 轮对话，关闭连接
   - 第二次 with 块：用相同 thread_id invoke，验证之前的状态被加载
   - 验证第二次 invoke 后 messages 包含第一轮的 Q+A

5. **thread_id 隔离**：
   - 两个不同 thread_id 各自独立，互不影响

6. **get_state_history**（时间旅行调试）：
   - 多轮对话后，get_state_history 返回多个 StateSnapshot
   - 每个 snapshot 对应一个检查点

---

## 代码蓝图：施工图纸级别

### checkpointer.py

```python
"""检查点持久化模块 — 为 LangGraph 工作流提供状态持久化能力。

本模块封装 SqliteSaver 的创建和初始化逻辑，通过上下文管理器模式
管理数据库连接生命周期。

核心设计：
1. **上下文管理器模式**：包装 SqliteSaver.from_conn_string，
   确保连接在退出时正确关闭
2. **依赖倒置**：返回 BaseCheckpointSaver 抽象类型，
   预留 PostgresSaver 扩展接口
3. **防御性初始化**：自动创建数据库目录 + 调用 setup()

为什么独立为模块而非放在 builder.py 中（设计决策）：
    1. 职责单一：checkpointer.py 负责"创建和初始化检查点"，
       builder.py 负责"组装图"
    2. 生命周期隔离：checkpointer 是资源（数据库连接），
       其生命周期由调用方管理，不应与图的构建逻辑耦合
    3. 可替换性：未来切换 PostgresSaver 只需修改此模块

面试知识点：
    - Checkpointer 的作用：每次节点执行后自动保存状态快照，
      支持流程暂停/恢复、时间旅行调试、多会话隔离
    - MemorySaver vs SqliteSaver vs PostgresSaver：
      MemorySaver 仅内存存储，进程重启即丢失；
      SqliteSaver 本地文件持久化，适合单机生产；
      PostgresSaver 支持分布式部署
    - thread_id 的作用：通过 config["configurable"]["thread_id"]
      区分不同会话，同一 thread_id 的所有调用共享状态历史
"""
```

#### create_checkpointer

```python
@contextmanager
def create_checkpointer(settings: Settings) -> Iterator[BaseCheckpointSaver]:
    """创建检查点管理器（上下文管理器模式）。

    为什么用上下文管理器而非普通工厂函数（设计决策）：
        SqliteSaver.from_conn_string 是 @contextmanager，
        在退出时自动关闭 sqlite3 连接。本函数包装它，
        确保调用方无需关心连接清理细节。
        如果绕过 from_conn_string 直接创建 SqliteSaver(conn)，
        调用方必须自行管理连接关闭——这是资源泄漏的常见来源。

    为什么返回 BaseCheckpointSaver 而非 SqliteSaver（DIP）：
        依赖倒置——调用方依赖抽象类型而非具体实现。
        未来切换 PostgresSaver 时，只需修改此函数，
        调用方代码无需变更。

    为什么在内部调用 setup() 而非让调用方调用（封装）：
        setup() 是数据库初始化细节（创建表），属于检查点创建的
        原子操作。setup() 是幂等的（重复调用安全），在内部调用
        不会产生副作用。若留给调用方，遗忘调用会导致运行时异常
        （表不存在），且错误信息不直观。

    为什么自动创建目录而非依赖部署约定（鲁棒性）：
        sqlite3.connect 不会创建父目录，目录不存在时抛出
        FileNotFoundError。自动创建是防御性编程，避免因
        部署环境差异（如全新机器上首次运行）导致启动失败。

    Args:
        settings: 全局配置实例，读取 checkpoint_db_path

    Yields:
        配置好的检查点管理器实例（BaseCheckpointSaver 子类）

    Example:
        with create_checkpointer(settings) as checkpointer:
            graph = build_graph(settings, checkpointer=checkpointer)
            result = graph.invoke(
                {"messages": [HumanMessage(content="你好")]},
                config={"configurable": {"thread_id": "session-1"}},
            )
    """
    # 步骤 1：提取数据库路径
    #   db_path = settings.checkpoint_db_path

    # 步骤 2：确保数据库目录存在
    #   调用 os.makedirs，传入 os.path.dirname(db_path)，设置 exist_ok=True
    #   为什么：sqlite3.connect 不会自动创建父目录，
    #   若目录不存在会抛出 FileNotFoundError
    #   边界：os.path.dirname("checkpoints.db") 返回 "" → makedirs 抛异常
    #   处理：仅当 dirname 非空时调用 makedirs

    # 步骤 3：调用 SqliteSaver.from_conn_string，传入 db_path
    #   返回上下文管理器，使用 with 语句进入
    #   日志：info 记录检查点管理器创建中、db_path

    # 步骤 4：调用 checkpointer.setup() 初始化数据库表
    #   为什么首次必须调用：创建 checkpoints 等必要表
    #   为什么重复调用安全：setup() 内部检查表是否存在（幂等）

    # 步骤 5：日志：info 记录检查点管理器初始化完成、db_path

    # 步骤 6：yield checkpointer
    #   with 块退出时，from_conn_string 自动关闭 sqlite3 连接
```

---

### builder.py 修改

#### 现有测试适配

`build_graph` 新增 `checkpointer: BaseCheckpointSaver | None = None` 参数有默认值，
因此现有调用方（`_build_graph_with_mocks()` helper、`build_graph(settings)` 调用）
**无需修改**——默认 `checkpointer=None` 保持向后兼容。
新测试（`test_workflow_checkpointer.py`）需独立的 helper，
接受可选 checkpointer 参数。

#### build_graph 签名变更

```python
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
        详见 design.md 决策 2。核心理由：checkpointer 是资源（数据库连接），
        其生命周期需要由调用方管理（何时打开、何时关闭）。
        build_graph 只负责"组装图"，不负责"管理资源"。

    Args:
        settings: 全局配置实例
        checkpointer: 可选的检查点管理器。传入后支持状态持久化，
            调用 invoke 时需传入 config={"configurable": {"thread_id": "xxx"}}

    Returns:
        编译后的 CompiledStateGraph
    """
```

#### build_graph 步骤 6 修改

```python
    # 第6步：编译并返回
    # 调用 graph.compile，传入 checkpointer=checkpointer
    #   注入：checkpointer（可 Mock，可传 None）
    #   checkpointer=None 时等价于之前的行为（无持久化）
    # 日志：info 记录工作流图构建完成、has_checkpointer 字段
    # 返回 compiled
```

---

### \_\_init\_\_.py 更新

```python
"""workflow 包 — LangGraph 工作流定义。

本包定义 LangGraph 的状态结构、节点函数、图构建逻辑、检查点持久化。

公共 API：
    - GraphState：工作流全局状态（TypedDict）
    - create_workflow_nodes：工厂函数，创建节点
    - build_graph：图构建函数，组装并编译工作流
    - create_checkpointer：检查点管理器工厂（上下文管理器）
"""

from src.workflow.builder import build_graph
from src.workflow.checkpointer import create_checkpointer
from src.workflow.nodes import create_workflow_nodes
from src.workflow.state import GraphState

__all__ = [
    "GraphState",
    "build_graph",
    "create_checkpointer",
    "create_workflow_nodes",
]
```

---

## 常见坑点

1. **from_conn_string 是上下文管理器**：不能直接 `checkpointer = SqliteSaver.from_conn_string(path)` 获取实例，必须用 `with` 语句。直接调用返回的是 Generator 对象，不是 SqliteSaver——调用其方法会抛 `AttributeError`。

2. **setup() 必须在首次 invoke 前调用**：不调用 setup() 会导致数据库表不存在，invoke 时抛出 `sqlite3.OperationalError: no such table: checkpoints`。setup() 是幂等的，重复调用安全——内部会检查表是否存在。

3. **使用 checkpointer 时 thread_id 是必须的**：`graph.invoke(input, config={"configurable": {"thread_id": "xxx"}})`。不传 `configurable.thread_id` 会抛出 `MissingRequiredKeyError` 或类似配置错误。不使用 checkpointer 时（`checkpointer=None`），config 是可选的。

4. **add_messages reducer 与 checkpointer 的交互**：使用 checkpointer 后，同一 thread_id 的多次 invoke 会自动累积 messages（add_messages reducer 合并新旧消息）。调用方不需要手动管理对话历史——这是 checkpointer 的核心价值。

5. **Ctrl+C 时的检查点状态**：LangGraph 在每个节点执行完成后保存检查点。Ctrl+C 可能在一个节点执行过程中触发。此时最后一个完成节点的状态已保存，但当前执行中的节点修改会丢失。重启后使用相同 thread_id 调用 invoke，图会从最后一个完成节点的检查点继续。

6. **目录不存在导致 sqlite3.connect 失败**：`sqlite3.connect("db/checkpoints.db")` 要求 `db/` 目录已存在，否则抛出 `FileNotFoundError`（实际上是 `OperationalError`，取决于 SQLite 版本）。create_checkpointer 内部确保目录存在。

7. **:memory: 数据库不支持中断恢复测试**：`:memory:` SQLite 数据库的数据在连接关闭后丢失。测试中断恢复场景必须使用文件数据库（临时文件）。

8. **checkpointer=None 与 checkpointer=SqliteSaver 的行为差异**：前者 `graph.invoke(input)` 可直接调用；后者必须 `graph.invoke(input, config={"configurable": {"thread_id": "..."}})`。这个差异在向后兼容性测试中需要覆盖。
