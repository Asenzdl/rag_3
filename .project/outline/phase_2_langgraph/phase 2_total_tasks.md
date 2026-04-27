# Phase 2：LangGraph 骨架 + 对话记忆

总目标：将 Phase 1 的 LCEL 链迁移到 LangGraph 状态图架构，实现多轮对话记忆、条件路由、检查点持久化，为后续高级检索策略和工具调用打下坚实架构基础。

## Phase 2 完成后的交付物清单

- LangGraph 工作流：src/workflow/ 下完整的图定义、节点、条件边和检查点配置。
- 持久化对话：db/checkpoints.db 保存所有会话的检查点，支持会话恢复。
- 对话记忆管理：src/memory/ 下的裁剪和摘要函数，已集成到生成节点。
- 自适应路由：文档评估 + 查询重写循环，为 Phase 4 工具调用预留接口。
- 升级的 CLI：支持多轮对话、会话恢复、流式输出。
- 端到端测试：覆盖多轮对话和条件分支逻辑。

## Task 2.1 LangGraph 状态定义Task 2.2 核心节点函数实现

### 任务目标

实现 LangGraph 工作流的三个核心节点：路由节点（意图分类）、检索节点、生成节点。

### 涉及文件

- `src/workflow/nodes.py`
- `src/workflow/routing.py`（路由逻辑独立）

### 面试级知识点

- **节点的函数签名**：LangGraph 节点函数接收 `state: GraphState`，返回 `Partial[GraphState]` 或 `dict`，仅需返回需要更新的字段。
- **节点职责单一原则**：每个节点只做一件事——路由节点只做意图分类，检索节点只做检索，生成节点只做生成。这样便于单独测试和替换。
- **条件边的路由函数**：返回字符串标签（如 `"retrieve"`、`"generate"`、`"end"`），图中通过映射表将标签映射到目标节点。

### 生产级注意事项

- **意图分类的 Prompt 设计**：路由节点使用轻量 Prompt（如"判断用户问题是问候、知识库问题还是无法回答"），分类结果决定后续分支，避免每次都走完整 RAG 流程。
- **检索节点复用 Phase 1 的** `BaseRetriever`：不重新实现检索逻辑，直接调用 `base_retriever.retrieve()`，保持代码 DRY。
- **生成节点中的迭代计数**：每次进入生成节点时 `iteration_count += 1`，配合条件边限制最大重试次数，防止无限循环。
- **节点内异常处理**：每个节点应捕获已知异常（如检索失败、LLM 超时），返回带有错误信息的状态更新，而非让整个图崩溃。

### 验收标准

- 三个节点函数可独立运行：给定模拟的 `GraphState`，每个节点能正确返回更新后的状态字典。
- 路由节点对 5 个测试问题（2 个问候、3 个知识库问题）的分类准确率 100%。
- 检索节点返回的 `documents` 字段包含 `List[Document]`，每个文档带有 `source` 元数据。

### 任务目标

定义 LangGraph 工作流的全局状态结构，作为所有节点间数据传递的唯一载体。

### 涉及文件

- `src/workflow/state.py`

### 面试级知识点

- **StateGraph 的三要素**：`StateGraph` 是 LangGraph 的核心构建块，通过节点、边和状态构造复杂工作流。状态在节点间传递，每个节点读取并返回更新后的状态。
- **TypedDict + Annotated 组合**：使用 `TypedDict` 定义状态字段类型，`Annotated` 配合 `add_messages` reducer 实现消息列表的增量追加而非覆盖。
- **StateGraph vs MessageGraph**：`MessageGraph` 是 `StateGraph` 的特化版本，状态仅包含 `messages` 字段；自定义 `StateGraph` 可扩展更多字段（如 `documents`、`iteration_count`）。

### 生产级注意事项

- **reducer 函数的选择**：对于 `messages` 字段必须使用 `add_messages`，确保每次节点返回的消息被追加而非覆盖；对于 `documents` 字段，根据业务需求选择覆盖或合并策略。
- **状态字段精简原则**：状态中只存储跨节点需要传递的数据，临时变量在节点内部处理。字段过多会增加序列化开销和检查点存储成本。
- **类型提示完整性**：所有字段必须有明确的类型注解，便于 IDE 提示和静态检查，减少运行时错误。

### 验收标准

- 定义 `GraphState` TypedDict，至少包含 `messages`（`Annotated[list, add_messages]`）、`documents`（`List[Document]`）、`iteration_count`（`int`）。
- 编写单元测试验证 `add_messages` reducer 的正确行为：连续两个节点返回消息列表，状态中的 `messages` 应包含两者合并结果。
- 状态定义文件可被 `nodes.py` 和 `builder.py` 正常导入，无循环依赖。



## Task 2.2 核心节点函数实现

### 任务目标

实现 LangGraph 工作流的三个核心节点：路由节点（意图分类）、检索节点、生成节点。

### 涉及文件

- `src/workflow/nodes.py`
- `src/workflow/routing.py`（路由逻辑独立）

### 面试级知识点

- **节点的函数签名**：LangGraph 节点函数接收 `state: GraphState`，返回 `Partial[GraphState]` 或 `dict`，仅需返回需要更新的字段。
- **节点职责单一原则**：每个节点只做一件事——路由节点只做意图分类，检索节点只做检索，生成节点只做生成。这样便于单独测试和替换。
- **条件边的路由函数**：返回字符串标签（如 `"retrieve"`、`"generate"`、`"end"`），图中通过映射表将标签映射到目标节点。

### 生产级注意事项

- **意图分类的 Prompt 设计**：路由节点使用轻量 Prompt（如"判断用户问题是问候、知识库问题还是无法回答"），分类结果决定后续分支，避免每次都走完整 RAG 流程。
- **检索节点复用 Phase 1 的** `BaseRetriever`：不重新实现检索逻辑，直接调用 `base_retriever.retrieve()`，保持代码 DRY。
- **生成节点中的迭代计数**：每次进入生成节点时 `iteration_count += 1`，配合条件边限制最大重试次数，防止无限循环。
- **节点内异常处理**：每个节点应捕获已知异常（如检索失败、LLM 超时），返回带有错误信息的状态更新，而非让整个图崩溃。

### 验收标准

- 三个节点函数可独立运行：给定模拟的 `GraphState`，每个节点能正确返回更新后的状态字典。
- 路由节点对 5 个测试问题（2 个问候、3 个知识库问题）的分类准确率 100%。
- 检索节点返回的 `documents` 字段包含 `List[Document]`，每个文档带有 `source` 元数据。



## Task 2.3 条件边与图构建

### 任务目标

使用 `StateGraph` 构建完整的问答工作流，包含条件分支和循环逻辑。

### 涉及文件

- `src/workflow/builder.py`
- `src/workflow/edges.py`

### 面试级知识点

- `add_node` **+** `add_edge` **+** `add_conditional_edges`：LangGraph 的图构建三部曲——先添加所有节点，再连接边，条件边通过路由函数决定下一跳。
- **START 和 END 常量**：`START` 表示图的入口节点，`END` 表示终止；必须显式连接，否则图无法编译。
- **循环与递归限制**：通过 `RunnableConfig` 中的 `recursion_limit` 控制最大迭代次数（默认 25），防止死循环。
- **CompiledGraph**：`compile()` 将 `StateGraph` 转换为可执行的 `CompiledGraph`，支持 `invoke`、`stream`、`astream` 等运行方式。

### 生产级注意事项

- **条件边的路由函数必须幂等**：给定相同状态，路由函数应返回相同的标签，否则会导致不可预测的执行路径。
- **添加"安全阀"节点**：当 `iteration_count` 超过阈值时，强制跳转到 `END` 或返回预设回复，防止无限循环耗尽资源。
- **图编译检查**：`compile()` 会验证节点连接完整性和循环检测，编译失败时错误信息应友好提示缺失的边。
- **图的模块化组织**：将图构建逻辑封装在 `build_graph()` 函数中，返回 `CompiledGraph`，便于测试和不同环境配置。

### 验收标准

- 图包含以下节点：`route` → `retrieve` → `generate`，以及一个 `fallback` 节点处理无法回答的情况。
- 条件边逻辑：`route` 根据意图分类跳转到 `retrieve` 或 `fallback`；`generate` 后跳转到 `END`。
- 运行 `builder.build_graph()` 能成功编译，无节点未连接或循环检测错误。
- 使用 `graph.get_graph().draw_mermaid_png()` 生成流程图，视觉验证图结构正确。



## Task 2.4 检查点持久化（Checkpointer）

### 任务目标

为 LangGraph 工作流添加检查点持久化能力，支持多轮对话状态保存、恢复和时间旅行调试。

### 涉及文件

- `src/workflow/checkpointer.py`

### 面试级知识点

- **Checkpointer 的作用**：每次节点执行后自动保存状态快照，支持流程暂停/恢复、时间旅行调试、多会话隔离。
- **MemorySaver vs SqliteSaver vs PostgresSaver**：`MemorySaver` 仅内存存储，进程重启即丢失；`SqliteSaver` 本地文件持久化，适合单机生产；`PostgresSaver` 支持分布式部署。
- **thread_id 的作用**：通过 `config["configurable"]["thread_id"]` 区分不同会话，同一 thread_id 的所有调用共享状态历史。

### 生产级注意事项

- **Phase 2 使用** `SqliteSaver`：比 `MemorySaver` 更接近生产环境，同时无需额外部署 PostgreSQL，降低复杂度。
- **检查点数据库路径**：将 SQLite 文件存放在 `db/checkpoints.db`，与向量库 `db/chroma/` 同级管理。
- **检查点清理策略**：LangGraph 支持 TTL（Time-to-Live）配置，可设置检查点自动过期，防止数据库无限膨胀。
- **并发会话隔离**：不同用户使用不同 `thread_id`，检查点自动按 thread 隔离，互不干扰。

### 验收标准

- 使用 `SqliteSaver.from_conn_string("db/checkpoints.db")` 创建检查点。
- 进行一轮多轮对话（3 个问题），每次调用时传入相同 `thread_id`，验证对话历史被正确累积。
- 使用 `graph.get_state(config)` 能获取到当前会话的完整状态快照。
- 模拟中途中断（Ctrl+C 后重启），使用相同 `thread_id` 调用 `graph.invoke` 能从上次断点继续。

### Task 2.5 对话记忆管理（短期 + 摘要压缩）

### 任务目标

实现对话历史的智能管理，包括短期记忆的滑动窗口裁剪和长对话的摘要压缩，防止上下文窗口溢出。

### 涉及文件

- `src/memory/conversation.py`
- `src/memory/summary.py`

### 面试级知识点

- **短期记忆 vs 长期记忆**：短期记忆管理活跃会话中的即时信息，通常以消息列表形式存储在状态中；长期记忆跨会话持久化用户偏好和知识。
- **上下文窗口的"RAM 类比"**：LLM 的上下文窗口类似操作系统的 RAM，需要决策哪些数据应载入——这正是上下文工程的核心任务。
- **摘要触发时机**：当消息列表的 token 数超过阈值（如 4000）时，调用 LLM 将历史消息压缩为一段摘要，替换原始消息以释放空间。
- **滑动窗口裁剪**：最简单的记忆策略——只保留最近 N 轮对话，超出部分直接丢弃。

### 生产级注意事项

- **结合状态中的** `messages` **字段**：LangGraph 的 `add_messages` reducer 已自动维护消息历史，记忆模块只需提供"裁剪"或"摘要"函数，在节点中调用。
- **摘要函数的幂等性**：摘要生成应缓存结果，避免相同对话历史被重复摘要（增加成本和延迟）。
- **指代消解**：当用户追问"它怎么用？"时，需要将"它"解析为上一轮提到的具体实体。这可以通过在 Prompt 中注入最近对话历史来实现，而非依赖复杂的 NLP 处理。
- **Token 计数准确性**：使用 `tiktoken` 精确计算消息列表的 token 数，而非简单按字符估算，因为中文和代码块的 token 消耗差异巨大。

### 验收标准

- 实现 `trim_conversation_history(messages, max_tokens=4000)` 函数，返回裁剪后的消息列表。
- 实现 `summarize_conversation(messages, llm)` 函数，当消息超过阈值时返回摘要消息（`AIMessage` 类型，content 为摘要文本）。
- 在生成节点中集成记忆管理：每次生成前检查消息列表长度，触发裁剪或摘要。
- 编写单元测试验证：给定 20 条模拟消息，`trim_conversation_history` 返回的消息列表 token 数 ≤ 4000。



## Task 2.6 文档评估与自适应路由

### 任务目标

增加文档评估节点，判断检索结果的相关性，不相关时触发查询重写或网络搜索（为 Phase 4 工具调用预留接口）。

### 涉及文件

- `src/workflow/nodes.py`（新增 `grade_documents` 节点）
- `src/workflow/edges.py`（新增评估分支）

### 面试级知识点

- **ReAct 模式在 RAG 中的应用**：ReAct 代理通过"推理→行动→观察"循环处理复杂任务。文档评估节点相当于"观察"阶段——检查检索结果是否满足需求，决定是否需要进一步行动。
- **条件边与动态路由**：LangGraph 的条件边可根据状态内容（如评估分数）动态选择下一节点，实现自适应流程。
- **查询重写策略**：当评估结果不相关时，调用 LLM 将原始查询改写为更精确的表述，重新检索。这是 MultiQuery 和 HyDE 的基础逻辑。

### 生产级注意事项

- **评估 Prompt 的二元判断**：使用简单的"相关 / 不相关"二元判断，而非多级评分，降低 LLM 判断的不确定性。Prompt 示例："给定用户问题和检索到的文档片段，判断文档是否包含回答问题所需的信息。仅回答 YES 或 NO。"
- **重写循环次数限制**：通过状态中的 `rewrite_count` 字段限制最大重写次数（建议 ≤ 2），防止无限循环。
- **为工具调用预留接口**：当重写次数耗尽或评估仍不相关时，跳转到 `tool_call` 节点（Phase 4 实现），目前可先跳转到 `fallback` 节点。
- **评估节点的性能开销**：每次检索后额外调用一次 LLM，增加约 1-2 秒延迟和 token 成本。可通过缓存评估结果（相同 query + 相同文档集合）来优化。

### 验收标准

- 实现 `grade_documents` 节点，接收 `state`，返回 `grade` 字段（`"relevant"` 或 `"not_relevant"`）。
- 添加条件边：`grade == "relevant"` → 跳转到 `generate`；`grade == "not_relevant"` → 跳转到 `rewrite` 节点。
- `rewrite` 节点调用 LLM 改写查询，`rewrite_count += 1`，跳回 `retrieve` 节点。
- 测试场景：故意提出一个向量库中没有的问题（如"LangChain 如何与区块链集成？"），系统应进入重写循环，最终因 `rewrite_count` 超限跳转到 `fallback` 并返回"根据现有文档，我无法回答该问题"。

## Task 2.7 CLI 升级与端到端测试（多轮对话）

### 任务目标

升级 CLI 入口，支持 LangGraph 工作流的多轮对话交互，并完成端到端功能验证。

### 涉及文件

- `src/app.py`
- `tests/test_e2e_graph.py`

### 面试级知识点

- `graph.stream()` **vs** `graph.invoke()`：`invoke` 返回最终状态，适合批量处理；`stream` 逐节点返回中间状态，适合实时展示和流式输出。
- **多轮对话的** `thread_id` **管理**：CLI 会话开始时生成唯一 `thread_id`，整个会话期间复用，确保对话历史连贯。
- **中断与恢复**：LangGraph 支持 `interrupt` 机制实现人机协作（如人工审核），但 RAG 场景中较少使用，了解即可。

### 生产级注意事项

- **流式输出的用户体验**：使用 `graph.astream` 异步流式执行，配合 `astream_events` 捕获生成节点的 token 级流式输出，实现打字机效果。
- **优雅处理** `KeyboardInterrupt`：捕获 Ctrl+C 后保存当前检查点，提示用户"对话已保存"，而非直接退出丢失状态。
- **命令行参数支持**：通过 `argparse` 支持 `--thread-id` 参数，允许用户恢复之前的会话。
- **日志中记录** `thread_id`：每条日志绑定 `thread_id`，便于追踪单个会话的完整执行链路。

### 验收标准

- 启动 `python src/app.py`，连续进行 5 轮问答（包含追问、指代消解场景），程序不崩溃，对话历史正确保留。
- 输入 `exit` 后正常退出，检查点已持久化到 `db/checkpoints.db`。
- 使用 `--thread-id` 参数恢复之前的会话，能继续之前的对话上下文。
- 运行 `pytest tests/test_e2e_graph.py` 通过全部端到端测试用例，覆盖：简单问答、追问、文档评估不相关分支、重写循环退出。