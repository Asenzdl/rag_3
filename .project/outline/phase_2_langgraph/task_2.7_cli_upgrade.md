# Task 2.7 CLI 升级与端到端测试（多轮对话）

## 任务目标
将 CLI 入口从 Phase 1 RAGChain 切换为 Phase 2 LangGraph 工作流，实现多轮对话交互（含流式输出、会话恢复），并编写覆盖主要路径的端到端测试。

## 涉及文件
- `src/app.py`（**新文件**，替换当前 `app.py` → 重命名为 `chain_app.py`）—— Phase 2 LangGraph CLI 主入口
- `src/chain_app.py`（**重命名自** 当前 `app.py`）—— Phase 1 RAGChain CLI，保留不动
- `tests/test_e2e_graph.py`（**新文件**）—— LangGraph 端到端测试
- `tests/conftest.py`（**新文件**，可选）—— 共享测试 fixtures（`_build_graph_with_mocks`、`FakeChatModel`、`_invoke_with_thread_id`）
- `tests/test_e2e.py`（**不动**）—— Phase 1 e2e 测试，import 路径需更新为 `chain_app`

### CLI 文件分离决策
Phase 1（RAGChain）和 Phase 2（LangGraph）CLI 必须分离到不同文件：
- **`chain_app.py`**：保留 Phase 1 的 RAGChain CLI（含 `ChatSession`、`cli_loop`、`main`）
  - 为什么保留：Phase 1 实现是可工作的基线，保留意味着可以随时回退对比，也是历史 reference
- **`app.py`**（新写）：Phase 2 LangGraph CLI，成为项目的主入口
  - 为什么用 `app.py` 这个名字：项目根 `run.py` 和测试文件均 import `src.app`，保持接口一致
- `tests/test_e2e.py` 的 import 从 `from src.app` 改为 `from src.chain_app`（仅 import 路径变更，测试逻辑不动）

## 设计指导
- 官方文档：langgraph mcp（`stream` / `stream_mode` / `messages` mode / checkpointer + stream 兼容性）
- context7：LangGraph 1.1+ `stream(version="v2", stream_mode=...)` API，`StreamPart` 统一格式 `{type, ns, data}`
- 参考模式：当前 `tests/test_e2e.py` 的 Mock chain + `patch("builtins.input")` + `capsys` CLI 测试模式
- 参考模式：当前 `tests/test_workflow_checkpointer.py` 的 `_invoke_with_thread_id` + 多轮对话测试模式

## 面试级知识点

### 1. `graph.stream()` vs `graph.invoke()` —— 两种执行模式的设计哲学
- **`invoke(version="v2")`**：返回 `GraphOutput.value`，即最终状态。一次性、全有或全无。适合批量处理、后台任务、API 非流式响应。
- **`stream(version="v2", stream_mode=...)`**：返回 `StreamPart` 迭代器，每个 part 是一个 `{type, ns, data}` 字典。v2 模式下无论组合多少种 stream_mode，格式统一。
- **机制差异**：两者在 LangGraph 内部走同一 Pregel 引擎，区别仅在于"是否在每个 super-step 后 yield 中间结果"。invoke(version="v2") 等价于 stream(version="v2") 后丢弃中间值只取最后一个。
- **方案对比**：`invoke` 简单但用户等待期间无反馈（"黑盒等待"）；`stream` 提供渐进式反馈，用户感知延迟更低，但调用方需处理迭代器生命周期。
- **本项目选型**：CLI 交互场景默认用 `stream(version="v2")` + `stream_mode="messages"` 实现打字机效果，保留 `--no-stream` 开关回退到 `invoke(version="v2")`。

### 2. `stream_mode` 四种模式 —— 什么时候该用什么
- **`"values"`**：每个 super-step 后的完整状态快照。输出冗长，适合调试/观察状态演进，不适合生产 CLI（会把整个 messages 列表逐轮打印）。
- **`"updates"`**：`{node_name: {changed_keys}}` —— 只展示每个节点改了什么。最简洁的模式，适合日志/监控，但不含 token 级增量。
- **`"messages"`**：`(message_chunk, metadata)` 元组，metadata 包含 `langgraph_node` 标识来源节点。**关键发现**：即使 LLM 在节点内使用 `.invoke()`（非 `.stream()`），LangGraph 在 Pregel 层自动产出 token 级消息事件。这是实现打字机效果的正确方式，无需 `astream_events()`。
  - ⚠️ **必须配合 `version="v2"`**：`stream_mode="messages"` 仅在 `stream(..., version="v2")` 下生效。默认 version 为旧版兼容格式，messages mode 行为不确定。
- **`"custom"`**：节点内通过 `stream_writer` 主动写入的自定义数据。用于传递非消息类型的增量数据（如进度百分比）。
- **组合使用**：`stream(version="v2", stream_mode=["messages", "custom"])` 可同时获取 token 输出和自定义事件，LangGraph 自动合并为统一 StreamPart 流。**`version="v2"` 是组合多 mode 的前提**——v1 模式下多 mode 返回格式不统一（tuple），v2 才统一为 `{type, ns, data}`。

### 3. `stream_mode="messages"` 的 token 级流式 —— 为什么不需要 `astream_events()`
- **旧方式（LangChain）**：`chain.astream_events()` 或 `RunnableConfig` callback 捕获 `on_llm_new_token` —— 需要手动配置回调，事件格式因链结构而异。
- **新方式（LangGraph 1.1+，`version="v2"`）**：直接在 Pregel 层拦截 LLM 输出流，无论节点内部用 `ainvoke` 还是 `astream`，框架统一产出 `(AIMessageChunk, metadata)` 元组。
- **过滤技巧**：`metadata["langgraph_node"] == "generate"` 精确取 generate 节点的输出，排除 route / grade / rewrite 等内部节点的 LLM 调用。
- **方案对比**：`astream_events()` 是 LangChain 层的机制，需要在节点代码中配合使用；`stream_mode="messages"` 是 LangGraph 框架层能力，对节点代码透明。后者更简洁、侵入性更低。

### 4. `thread_id` 管理 —— 多轮对话的状态钥匙
- **机制**：LangGraph 的 checkpointer 以 `thread_id` 为主键索引状态。同一 `thread_id` 的连续调用自动加载历史状态（messages 列表、checkpoint metadata），实现"无感续聊"。
- **生成策略**：新会话用 `uuid.uuid4().hex[:8]`（8 位 hex，兼顾唯一性和可读性），通过 `--thread-id` 参数传入则复用已有会话。
- **传递方式**：`config = {"configurable": {"thread_id": thread_id}}`，每次 `stream(version="v2")` 或 `invoke(version="v2")` 传入同一 config 对象。
- **隔离性**：不同 `thread_id` 的状态完全隔离，不会互相污染。这是多租户场景的基础能力。
- **方案对比**：前端管理（客户端记住 thread_id）vs 后端管理（服务端维护 session-id 映射）。本项目 CLI 场景选前端管理——简单直接，无需额外存储。

### 5. Checkpointer + stream 的兼容性 —— 中断安全
- **兼容性**：100% 兼容。checkpoint 在每次 super-step 边界自动保存，无论使用 `invoke(version="v2")` 还是 `stream(version="v2")`，保存时机一致。
- **中断安全**：如果在 `stream(version="v2")` 迭代过程中发生 `KeyboardInterrupt`，最后一个完成的 super-step 的 checkpoint 已经持久化到 SQLite。下次用相同 `thread_id` 恢复时，从该 checkpoint 继续。
- **为什么不是"丢掉当前轮"**：stream 模式下中断可能发生在 generate 节点输出到一半时。此时 checkpointer 已保存 generate 节点执行前的状态（不含当前轮 AI 回复），恢复后相当于"上一轮对话完整，当前轮重新生成"。这是可接受的语义损失。
- **与 `invoke(version="v2")` 的差异**：invoke 是原子的——要么完全成功要么完全失败（异常时 checkpoint 未被写入），不会出现"半条消息"的脏状态。

### 6. CLI REPL 模式的分层异常处理
经典 REPL 循环有四个异常处理层，每层语义不同：
- **层 1（业务异常）**：`RAGSystemError` —— 系统已知错误（LLM 超时、检索失败），打印友好消息，**不退出**，继续等待下一个问题。
- **层 2（中断信号）**：`KeyboardInterrupt` / `EOFError` —— 用户主动退出，打印告别信息，**退出**循环。
- **层 3（未知异常兜底）**：`Exception` —— 未预期的错误，打印错误信息 + 日志记录，**不退出**，保持服务可用性。
- **层 4（初始化异常）**：`main()` 中捕获 —— 图编译失败等致命错误，打印错误，`sys.exit(1)`。
- **为什么层 1 和层 3 不退出**：一次请求失败不应终止整个会话。用户可能问了 10 个问题，第 11 个触发了 LLM 临时不可用——退出意味着前 10 轮的对话历史全部丢失。

### 7. 端到端测试的依赖隔离策略 —— FakeChatModel 与 MagicMock 的分工
- **`FakeChatModel(BaseChatModel)`**：完整模拟 LCEL `|` 管道场景（route、retrieve、rewrite、generate 节点）。继承 `BaseChatModel` 意味着可以走 `ainvoke` / `astream` / `_generate` 等标准路径。**限制**：不支持 `with_structured_output()`（会触发真实网络调用）、不支持 `_stream()` 覆写（除非手动实现）。
- **`MagicMock(spec=BaseChatModel)`**：用于 `with_structured_output()` 场景（grade 节点的 `grade_documents` 函数）。直接 mock 掉结构化输出的 schema 和返回值，绕过 LLM 调用。
- **为什么需要两种 mock**：`with_structured_output()` 在 LangChain 内部走不同的代码路径——它创建 `RunnableBinding` 而非走 `_generate`，导致 `FakeChatModel` 的子类方法不被调用。用 `MagicMock` 直接替换整个 LLM 实例更可靠。
- **共享化建议**：当前 `_build_graph_with_mocks()` 在两个测试文件中重复定义。建议提取到 `tests/conftest.py` 作为 fixture，消除代码重复。

### 8. 图编译与测试解耦 —— 为什么不在 `build_graph` 中硬编码 LLM/Retriever
- **当前设计**：`build_graph(settings, checkpointer=None)` 在函数内部调用 `create_llm(settings)` 和 `create_retriever(settings)` 创建真实依赖。
- **测试策略**：通过 `patch("src.workflow.builder.create_retriever", ...)` 和 `patch("src.workflow.builder.create_llm", ...)` 在 import 层替换工厂函数返回值，实现依赖注入。
- **为什么不传参注入**：`build_graph` 的接口简洁优先（2 个参数 vs 5+ 个参数），patch 方式将测试关注点收敛到 `builder` 模块，调用方无需感知内部依赖。
- **演进空间**：如果未来依赖种类继续增长，可在 `Settings` 上增加 `llm_factory` 和 `retriever_factory` callable 字段，实现配置驱动的依赖注入。

## 生产注意事项与优化

### 1. 流式输出的用户体验
- **实现方式**：`for chunk, metadata in graph.stream(..., version="v2", stream_mode="messages")`，过滤 `metadata["langgraph_node"] == "generate"`，每个 chunk 执行 `print(chunk.content, end="", flush=True)`。**`version="v2"` 不可省略**——缺省情况下 `stream_mode` 的行为随版本变化，且默认版本的 messages mode 行为未定义。
- **`flush=True` 的必要性**：Python 的 stdout 默认行缓冲。不 flush 时 token 积攒到换行符才输出，打字机效果失效。
- **异常回退**：如果 stream 中途抛异常（如网络断开），捕获后回退到 `invoke()` 获取完整结果，保证用户至少得到最终答案。
- **`subgraphs` 参数**：`stream(version="v2", subgraphs=False)` 不追踪子图事件。当前无子图时可省略，但如果 Phase 4 引入 agent 子图，需开启此参数观察子图内部事件。

### 2. 优雅退出与检查点保存
- **正常退出**（输入 `exit`/`quit`）：`stream(version="v2")` 完成当前轮后 break，checkpointer 已自动保存本次 super-step。
- **中断退出**（Ctrl+C）：KeyboardInterrupt 发生时，最后一个完成的 super-step 的 checkpoint 已持久化。退出前打印 `thread_id`，提示用户可用 `--thread-id <id>` 恢复。
- **为什么要打印 thread_id**：用户 Ctrl+C 时终端输出可能被中断信号打断，显式打印确保用户能看到恢复凭证。
- **上下文管理器**：如果 `create_checkpointer` 返回的是上下文管理器（如 SqliteSaver），在 `main()` 中用 `with` 包裹整个 REPL 生命周期，确保退出时连接正确关闭。

### 3. 命令行参数设计
使用 `argparse` 支持以下参数：
- `--thread-id <hex>`：恢复已有会话。不传则自动生成新的 8 位 hex UUID。
- `--no-stream`：关闭流式输出，回退到 `invoke(version="v2")` 模式。用于调试或非交互式终端。
- `--debug`：日志级别切换为 DEBUG，同时启用 `stream_mode="values"` 或 `"updates"` 打印每个节点的状态变化，便于排查问题。
- `--max-tokens <int>`：覆写 `GraphContext.max_tokens`（memory 触发阈值），默认 4000。
- **参数优先级**：CLI 参数 > 环境变量 > `settings.py` 默认值。这是配置管理的标准层级。

### 4. 结构化日志与 thread_id 绑定
- **每条日志绑定 thread_id**：`logger.info("...", thread_id=thread_id)`，确保多会话日志可追踪。
- **`structlog.contextvars.bind_contextvars(thread_id=...)`**：将 thread_id 绑定到整个请求上下文中，所有日志自动携带，无需每次手动传入。
- **关键日志点**：会话开始（thread_id 生成）、每轮问答开始/结束（question 截断 + turn count）、流式异常回退、会话退出。
- **日志中不记录完整 messages**：messages 列表可能很大，记录截断后的首条和末条消息即可。

### 5. 状态输入构造 —— 每轮只需传入当前问题
- **多轮对话的正确姿势**：每轮只传入 `{"messages": [HumanMessage(content=user_input)]}`，而非传入完整历史。
  - 为什么：checkpointer 自动从存储中加载历史 messages 并与新传入的合并（`add_messages` reducer），完整传入会导致消息重复。
- **`GraphContext` 与 `GraphState` 的初始化**：每轮 `stream(version="v2")` 调用只传 `HumanMessage`，`GraphState` 的其他字段（`question`、`documents` 等）由工作流内部节点写入，CLI 层不需要关心。
- **`max_rewrite_count` 从哪里来**：已在 `GraphState` 中有默认值（来自 `GraphContext.max_rewrite_count`），CLI 不需要传。如果 `--max-rewrite` CLI 参数需要覆写，可通过 `input` 参数传入 `{"max_rewrite_count": N}`。

### 6. 测试辅助代码共享化
当前存在代码重复问题，建议统一：
- **`_build_graph_with_mocks()`**：在 `test_workflow_builder.py` 和 `test_workflow_checkpointer.py` 中各有一份近乎相同的实现。提取到 `tests/conftest.py` 作为 `@pytest.fixture`。
- **`FakeChatModel`**：当前仅在 `test_workflow_nodes.py` 中内联定义。提取到 `tests/conftest.py`（或 `tests/factories.py`），供 e2e 测试复用。
- **`_invoke_with_thread_id()`**：当前在 `test_workflow_checkpointer.py` 中定义。同样提取到 conftest.py。
- **共享原则**：只提取被 2 个以上测试文件使用的 helper。单一文件专用的 helper 保留在原文件（避免过早抽象）。

### 7. CLI 输出的端到端验证
- **`patch("builtins.input", side_effect=iter([...]))`**：模拟用户逐轮输入。列表最后一个元素应为 `"exit"`。
- **`capsys` fixture**：捕获 stdout/stderr，验证输出包含预期文本（如回答关键词、来源 URL、thread_id 提示）。
- **流式输出的验证挑战**：`stream_mode="messages"` 产出的 token 是碎片化的（如 "Lang"、"Graph"、" 是"、" 一个"），不适合做精确字符串匹配。验证策略应改为：
  - 验证**输出不为空**（说明 stream 正常工作）
  - 验证**退出消息**出现（说明正常结束）
  - 验证**来源信息**出现在 stdout 中（说明 retrieval → generate 路径走通）
- **多轮上下文验证**：第二轮提问依赖第一轮的回答内容（如"上面提到的那个框架"），通过 `capsys` 检查第二轮输出是否包含相关关键词来验证上下文保持。

### 8. 降级与容错路径
- **stream 失败 → invoke 回退**：捕获 stream 迭代过程中的异常，自动切换到 `invoke()`。这应该对用户透明（或仅打印一条 warning）。
- **checkpointer 不可用时的行为**：如果 db 文件路径无写权限，`create_checkpointer` 应能优雅降级为内存模式（`:memory:`）或抛明确异常提示用户检查权限。
- **LLM 调用失败不中断 REPL**：与 Phase 1 行为一致——打印错误信息，logger 记录，continue 等待下一个问题。
- **空输入处理**：用户直接按回车应忽略（`continue`），不触发 LLM 调用，不消耗 token。

## 验收约束（可验证，不可协商）

- [ ] `python src/app.py` 启动 LangGraph CLI，连续进行 5 轮问答（包含追问、指代消解场景），程序不崩溃，每轮回复体现上下文理解（追问能正确关联前文）。退出后 `db/checkpoints.db` 中存在对应该会话的 checkpoint。
- [ ] 使用 `--thread-id <上一轮的id>` 恢复会话，提出的问题能关联恢复前的对话上下文（如直接引用"刚才说的那个"能正确理解），验证 checkpointer 的状态恢复正确。
- [ ] `--no-stream` 模式下，回答一次性完整输出（无逐 token 打字效果），功能与流式模式一致。
- [ ] 流式模式下，generate 节点的输出以 token 级渐进显示（打字机效果），非 generate 节点（如 route、grade）的内部 LLM 调用**不**输出到用户终端。
- [ ] `src/chain_app.py` 保留 Phase 1 CLI 功能不变，`python src/chain_app.py` 仍可正常启动 Phase 1 RAGChain REPL。`tests/test_e2e.py` 的 import 已更新为从 `chain_app` 导入，全部测试通过。
- [ ] 运行 `pytest tests/test_e2e_graph.py -v` 通过全部端到端测试用例，覆盖：简单问答、追问（指代消解）、文档评估不相关分支（触发 rewrite → grade 循环，达到上限后降级至 generate 输出诚实回应）、greeting 问候路径、fallback 降级路径、stream 中途异常回退 invoke。
- [ ] `KeyboardInterrupt`（Ctrl+C）不会导致脏状态：中断前已完成的轮次 checkpoint 已持久化，终端打印当前 `thread_id` 供恢复使用。
