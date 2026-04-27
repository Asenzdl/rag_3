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