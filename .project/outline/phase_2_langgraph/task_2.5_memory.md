### Task 2.5 对话记忆管理（短期 + 摘要压缩）

### 任务目标
实现对话历史的智能管理，包括短期记忆的滑动窗口裁剪和长对话的摘要压缩，防止上下文窗口溢出。

### 涉及文件
- `src/memory/conversation.py`（未创建）
- `src/memory/summary.py`（未创建）
- `src/workflow/nodes.py`（新增 memory 节点函数）
- `src/workflow/builder.py`（图拓扑加入 memory 节点）
- `tests/test_workflow_nodes.py`（新增 memory 节点测试）

### 面试级知识点
- **短期记忆 vs 长期记忆**：短期记忆管理活跃会话中的即时信息，通常以消息列表形式存储在状态中；长期记忆跨会话持久化用户偏好和知识。
- **上下文窗口的"RAM 类比"**：LLM 的上下文窗口类似操作系统的 RAM，需要决策哪些数据应载入——这正是上下文工程的核心任务。
- **摘要触发时机**：当消息列表的 token 数超过阈值（如 4000）时，调用 LLM 将历史消息压缩为一段摘要，替换原始消息以释放空间。
- **滑动窗口裁剪**：最简单的记忆策略——只保留最近 N 轮对话，超出部分直接丢弃。
- **RemoveMessage 机制**：LangGraph 的 `add_messages` reducer 识别 `RemoveMessage` 类型，从消息列表中删除指定 ID 的消息。这是 memory 节点写回处理结果的标准方式。
- **独立 memory 节点的优势**：职责单一（只做记忆管理）、可独立测试、Task 2.6 循环中可复用。

### 生产级注意事项（功能无须质疑，但具体实现必须质疑）
- **摘要降级策略**：`summarize_conversation` 调用 LLM 失败时，回退到 `trim_conversation_history`（丢弃最早的消息而非抛异常）。
- **Token 计数准确性**：使用 `tiktoken` 精确计算消息列表的 token 数，而非简单按字符估算，因为中文和代码块的 token 消耗差异巨大。
- **摘要函数的幂等性**：摘要生成应缓存结果，避免相同对话历史被重复摘要（增加成本和延迟）。
- **指代消解**：当用户追问"它怎么用？"时，需要将"它"解析为上一轮提到的具体实体。这可以通过在 Prompt 中注入最近对话历史来实现（`build_generate_messages` 的 `chat_history` 参数已提供此能力），而非依赖复杂的 NLP 处理。
- **图拓扑变更**：`retrieve → [memory] → generate`，memory 节点读取 `state["messages"]`，写回通过 `RemoveMessage` + 摘要/保留的消息。

### 验收标准（功能无须质疑，但具体实现必须质疑）
- 实现 `trim_conversation_history(messages, max_tokens=4000)` 函数，返回裁剪后的消息列表。
- 实现 `summarize_conversation(messages, llm)` 函数，当消息超过阈值时返回摘要消息（`AIMessage` 类型，content 为摘要文本）。
- 创建独立 memory 节点，在图拓扑中插入在 retrieve → generate 之间，负责检查消息列表长度并触发裁剪或摘要。
- memory 节点使用 `RemoveMessage` 写回处理结果，保留至少最近 2-4 条消息（含当前轮 HumanMessage）。
- 编写单元测试验证：给定 20 条模拟消息，`trim_conversation_history` 返回的消息列表 token 数 ≤ 4000。
