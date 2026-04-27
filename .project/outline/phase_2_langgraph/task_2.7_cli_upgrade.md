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