> **关联 Task**：Task 2.5 对话记忆管理
> **文档类型**：锚点
> **锚定决策**：D1（降级路径设计）、D4（计数精度对降级的影响）、D5（max_tokens 放 GraphContext）
> **覆盖的 Task 知识点**：REMOVE_ALL_MESSAGES + kept 在 reducer 中的执行时序、0.9 margin 的工程设计逻辑、summary 字段无压缩的失效边界、误差传播路径
> **关联文档**：[领航员](task_2.5_navigator.md) · [锚点① add_messages](task_2.5_anchor_01_add_messages.md) · [锚点② trim_messages](task_2.5_anchor_02_trim_and_count.md)

# 降级链路与可靠性边界

## 一个不起眼的 0.9

在 `memory_node` 的降级路径中：

```python
kept = trim_conversation_history(
    messages, max_tokens=int(max_tokens * 0.9)
)
```

`max_tokens * 0.9`。为什么是 0.9 不是 0.95 也不是 0.8？这个数字是拍脑袋的还是计算的？

## 0.9 的推导：降级路径的保守 margin

`max_tokens * 0.9` 出现在降级路径中——摘要失败后的保底处理。此时系统已处于不稳定状态（LLM 网络超时或 API 限流），需要快速完成裁剪并返回。

为什么用 0.9 而不是直接用 `max_tokens`？

1. **估算波动缓冲**：`count_tokens_approximately` 对不同语言内容的估算精度不同。10% 的 margin 吸收估算波动，确保降级后消息的 token 数严格小于阈值。

2. **end_on 不确定性的 buffer**：`end_on=("human",)` 在裁剪末尾移除孤立的 AIMessage，被移除消息的 token 数占用预算空间。0.9 在未重新计数的前提下提供安全边界。

3. **降级路径的哲学**：降级路径只求稳不求准。只要消息被压缩到安全范围、LLM 调用不超上下文窗口，比"刚好压缩到 4000 token"更重要。10% 的空间换可靠性。

0.9 是工程经验值——"留 10% 的 buffer 防止边缘情况"，不是精确公式推导的产物。更精确的做法应该用模型特定 tokenizer 重新计数验证，但这违背了降级路径的"快速"目标。0.9 是时间和精度的 trade-off。

## REMOVE_ALL_MESSAGES + kept 的执行时序

这是整个 memory 操作中最重要的交互细节。节点返回：

```python
{
    "messages": [
        RemoveMessage(id=REMOVE_ALL_MESSAGES),  # 清除全部
        *kept,                                     # 重建保留
    ],
}
```

在 `add_messages` reducer 中发生的事（详见锚点①）：

1. `left` = 旧消息列表（被 checkpoint 持久化的完整历史）
2. `right` = `[RemoveMessage("__remove_all__"), msg1, msg2, ...]`
3. 遍历 `right` 时遇到 `RemoveMessage(id=REMOVE_ALL_MESSAGES)`，记录 `remove_all_idx = 0`
4. 短路返回 `right[0 + 1:]` → `[msg1, msg2, ...]`
5. `state["messages"]` = `[msg1, msg2, ...]`

**关键约束**：`remove_all_idx + 1` 切片后，`kept` 中每条消息的 `id` 必须已经存在（不是 `None`），否则在接下来的图执行中，这些消息会被重新分配 UUID4，影响 `get_state()` 快照中消息 ID 的可预测性。

但在当前项目中，`kept` 中的消息是从 `state["messages"]` 中直接拿到的**原对象引用**——它们已经在之前的 reducer 调用中被分配过 UUID4。所以 `id` 不为 `None`。切片返回后，这些消息的 ID 保持不变，checkpoint 持久化时能正确存储。

**如果 `kept` 中包含 `id=None` 的新建消息呢？** 比如：

```python
kept = [SystemMessage(content="新的系统指令")]
```

这条消息的 `id` 是 `None`。在 `right` 中它会被分配一个新的 UUID4，然后作为 `state["messages"]` 的新状态。这本身不会报错，但它的 ID 与之前任何消息都不相同——即使内容和之前的 SystemMessage 完全一样，checkpoint 也认为它是"新消息"。

## 摘要成功路径 vs 降级路径的状态差异

两条路径返回的状态更新有本质区别：

| 维度 | 摘要成功路径 | 降级路径 |
|------|------------|---------|
| 返回值 | `{"messages": [...], "summary": new_summary}` | `{"messages": [...]}` |
| summary 字段 | **写入**新摘要 | **不写入**（保持原样） |
| 消息列表 | 摘要后保留的原对象 | trim 后保留的原对象 |

降级路径**不写入 summary**，这是有意设计：

- 摘要失败意味着 LLM 不可用。试图写入空的 summary 或用预设文本填充，都比不上保留旧的 summary 更有用。
- 保留旧 summary 可能不准确（遗漏了最新几轮对话），但不准确比空着好——LLM 至少知道之前对话的主题。
- 如果 trim 后立即再次触发 memory（消息又超限），系统会再次尝试摘要。此时 `state["summary"]` 仍保留旧值，摘要 prompt 中包含旧的上下文，增量扩展自然。

### 一个隐蔽的边缘情况

摘要成功后返回 `{"messages": [...], "summary": new_summary}`。注意 `new_summary` 来自 `summarize_conversation` 的返回值，不是从 `state` 中读取的。这意味着在节点返回被 reducer 合并到状态之前，`state["summary"]` 仍然是旧值。如果在同一个图执行步骤中其他节点读取 `state["summary"]`（不可能——memory 之后是 generate，同一轮图执行中 generate 在 memory 之后），它们读到的是旧值。

在 `retrieve → memory → generate` 的拓扑中，memory 和 generate 是同一轮的两个节点。generate 读取 `state.get("summary", "")`，但此时 memory 返回的 `{"summary": new_summary}` 已经被 reducer 合并了——因为 LangGraph 的节点执行是串行的，前一个节点的输出在下一个节点执行前已被合并到状态。

## summary 字段的膨胀问题

`state["summary"]` 是一个独立字段，不由 `add_messages` 管理（不是 `messages` 的子集），没有自己的压缩机制。

每次摘要成功，新摘要在旧摘要基础上扩展。随着对话增长，`summary` 字段本身会持续膨胀。可能的情况：

```
第 1 轮摘要：100 tokens
第 5 轮摘要：500 tokens
第 10 轮摘要：1200 tokens
第 20 轮摘要：3000 tokens（已经接近 max_tokens 阈值）
```

在 `build_generate_messages` 中，`summary` 被注入为 SystemMessage。当 summary 膨胀到 3000 tokens 时，仅 SystemMessage + summary 就占用了大量上下文预算。

### 为什么没有压缩

框架的 `summarize_conversation` 模式本身没有提供 summary 压缩——官档示例每次都做增量扩展：

```
"已有摘要" + "新消息" → "扩展后的摘要"
```

没有步骤检查"扩展后的摘要是否太长"。这是有意为之还是遗漏？推理如下：

1. summary 的增长速率远低于消息列表的增长。消息列表每轮增加 2 条（Human+AI），每条 ~200-500 tokens，而摘要每轮只增加 ~50-150 tokens 的信息量。要达到 4000 tokens，消息只需要 ~10 轮，而摘要需要 ~30 轮。

2. 当消息列表膨胀到触发 memory 的频率可以忽略时（每轮都触发），摘要的增长开始加速。此时可能是业务需要长期记忆的阶段——超出了 Task 2.5 短期记忆管理的范围。

### 如果摘要真的膨胀了怎么办

没有内置机制处理这个场景。可能的扩展方向：

- **对 summary 做二次摘要**：当 `len(summary) > max_tokens * 0.5` 时，用 LLM 压缩 summary 本身
- **round-robin 策略**：保留最近 K 轮消息 + 旧摘要，但限制摘要 ≤ max_tokens * 0.3
- **分层摘要**：将摘要按时间分片（第 1-10 轮、第 11-20 轮...），构建摘要链表

这些都是 Task 2.5 范围外的扩展。当前阶段，summary 膨胀到影响生成质量是合理的失效边界。

## 错误传播路径

### 摘要 LLM 失败

```
summarize_conversation 抛异常
  → memory_node 捕获 Exception
    → 降级为 trim_conversation_history
      → 返回 {"messages": [RemoveMessage(REMOVE_ALL), *kept]}
```

这个路径有两个隐含假设：

1. **摘要失败时 trim 不会失败**。`trim_conversation_history` 调用 `trim_messages`，是一个纯函数——不依赖 LLM、不依赖网络、不依赖外部资源。它的输入只有消息列表和阈值。如果 `trim_messages` 本身抛异常（比如 `token_counter` 参数错误），那是一个编程错误，不是运行时错误。所以 `trim_conversation_history` 不需要包在 `try/except` 中。

2. **摘要失败后系统仍能继续工作**。降级路径返回的 `kept` 列表是原始消息对象的子集，LLM 在 generate 节点中正常处理这些消息。用户不会感知到底层发生了降级——除了回答质量可能下降（上下文更少）。

### Token 计数 LLM 失败

`count_tokens_approximately` 不依赖 LLM，不会失败。

### `build_generate_messages` 中 summary 注入失败

`build_generate_messages` 在 `generate_node` 中被调用。如果 summary 字段中含有无法格式化的内容（理论上不可能——它是字符串），SystemMessage 的创建本身不会抛异常。

### 真正会崩溃的场景

1. **`add_messages` reducer 抛异常**：如果 `kept` 中包含非法消息类型（不是 BaseMessage 子类），`convert_to_messages` 会抛异常。这是编程错误，图会直接崩溃。
2. **`REMOVE_ALL_MESSAGES` 被误用**：如果在 `right` 中出现了两个 `RemoveMessage(id=REMOVE_ALL_MESSAGES)`，第一个触发短路，第二个永远不会被遍历到——没有影响。但如果在 `kept` 中也意外包含一个 `RemoveMessage` 对象，它的 ID 可能是某个 UUID4，正常情况下不等于 `REMOVE_ALL_MESSAGES`，但如果是复制粘贴错误导致 = `"__remove_all__"`，则 `kept` 列表会被截断。
3. **summary 字段跨越 checkpoint 边界后类型变化**：checkpoint 将字段值序列化/反序列化，如果 `summary` 在序列化后变成了 `None` 而非空字符串，`build_generate_messages` 中的 `if summary:` 判断为 `False`，摘要被静默跳过。

### 降级后 state 的一致性

降级路径不写 summary，这意味着 `state["summary"]` 保留的是**上一次摘要成功时的值**（如果有）。它与 `state["messages"]` 的内容存在差异：

- `state["summary"]` 描述了第 1-5 轮的对话
- `state["messages"]` 只包含第 4-5 轮的最近消息（被 trim 后的）

LLM 在 `build_generate_messages` 中同时接收到 summary（"对话是关于 X 的"）和具体消息（第 4-5 轮的细节），两者不完全重叠但也**不冲突**。summary 提供了摘要丢失的第 2-3 轮的上下文，具体消息提供了第 4-5 轮的精确信息。两者互补而非冗余。

只有当 trim 保留了第 1-3 轮的部分消息而 summary 描述了第 1-3 轮的摘要时，才会出现冗余——LLM 同时看到具体消息和它们的摘要。但这不会导致错误行为，只是浪费 token。

## 隐含前提汇总

此设计依赖以下前提，任何一个被违反都可能导致失效：

| 隐含前提 | 违反时的表现 | 诊断方法 |
|---------|------------|---------|
| `count_tokens_approximately` 不会严重低估 token 数 | 超出 LLM 上下文窗口 | 对比估算值和 `llm.get_num_tokens_from_messages()` |
| `trim_messages` 始终返回合法的 LLM 输入 | LLM 调用报 400 错误（非法消息序列） | 检查 `start_on`/`end_on` 是否覆盖所有消息类型 |
| `REMOVE_ALL_MESSAGES` 的字符串值不会和正常消息 ID 冲突 | 正常消息被意外清除 | 检查是否有消息 ID 等于 `"__remove_all__"` |
| summary 字段增长速度低于消息列表 | summary 膨胀到接近 `max_tokens` | 监控 `len(state["summary"])` |

## 面试要点

1. **0.9 margin 是工程经验值不是计算值**：设计文档不会写这个数字的来源，面试中需要能解释它是时间和精度 trade-off 的产物，不是精确计算的结果。

2. **REMOVE_ALL_MESSAGES + kept 的执行时序**：reducer 短路返回切片，`left` 完全丢弃。`kept` 中的原对象引用保留其已有 ID，checkpoint 一致性不受影响。

3. **降级路径不写 summary 是有意设计**：保留旧摘要的存活语义——不准确但比空着好，下一次摘要尝试时仍可增量扩展。

4. **summary 字段无压缩的失效边界**：系统性地做了 memory 压缩却漏掉了一个增长源（summary 本身）。面试追问"还有什么会无限增长"时，答出此点可展示边界思维。

5. **错误传播的隐藏假设**：摘要失败时 trim 不会失败（纯函数无外部依赖），但 trim 的 token 计数器如果配置错误是编程错误而非运行时错误，不会被降级路径捕获。
