### Task 2.5 对话记忆管理

### 任务目标
多轮对话中，消息列表不能无限增长。系统需要一种机制，在不破坏对话语义完整性的前提下，自动释放上下文窗口空间，确保 LLM 输入始终在有效 token 范围内。

### 验收约束（可验证，不可协商）
- 消息列表超过 token 阈值时，系统自动释放空间，不抛异常。阈值为 `max_tokens`放在 context_schema 中
- 释放后对话历史中不存在孤立的 AI 消息（每条 AI 消息都有对应的 Human 消息配对）
- LLM 摘要失败时自动降级，不中断工作流
- 摘要消息带有标记，显式告知 LLM 这不是原始对话而是经过压缩的
- 降级后必须确保消息列表 token 数降到阈值以下（而非"保留 N 条不管 token"）

### 面试知识点
- **短期 vs 长期记忆**：短期管理当前会话的即时信息，通常以消息列表形式存在；长期跨会话持久化偏好和知识。
- **上下文窗口的 RAM 类比**：LLM 的上下文窗口类似 RAM，需要决策哪些数据应载入——这是上下文工程的核心。
- **摘要触发时机**：当消息列表超过 token 阈值时，调用 LLM 将历史压缩为一段摘要。
- **增量摘要**：保留已有摘要，每次只对新消息做扩展，避免全量摘要的 O(n) 退化。
- **滑动窗口裁剪**：保留最近 N 轮对话，超出部分丢弃。最直接的释放策略。
- **RemoveMessage**：LangGraph 的 `add_messages` reducer 能识别 RemoveMessage，从消息列表中删除指定 ID 的消息。
- **独立 memory 节点的优势**：职责单一、可独立测试、可复用。

### 已知设计陷阱（阅读重点）
以下是在官档模式和普遍实践中反复出现的错误，实现时应注意：

1. **执行时间点**：memory 节点在 generate 之前执行，看不到当前轮完整的 Human+AI 配对。这可能导致不完整的裁剪决策。
2. **按条数不按轮次**：直接按消息条数裁剪会破坏 Human-AI 配对。必须以"对话轮次"为操作单元。
3. **压缩的有损性**：摘要压缩后原始信息永久丢失。LLM 不会知道自己看到的是压缩版本，需要显式标记。

### 最佳实践依据
- LangGraph 记忆管理（消息删除、裁剪、摘要）：https://docs.langchain.com/oss/python/langgraph/add-memory
- LangGraph RemoveMessage 模式：`langchain.messages.RemoveMessage` 配合 `add_messages` reducer
- LangGraph SummarizationNode（预构建摘要节点）：`langmem.short_term.SummarizationNode`
- LangChain 内置裁剪工具：`langchain_core.messages.utils.trim_messages`
