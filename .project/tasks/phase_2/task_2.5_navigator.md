> **关联 Task**：Task 2.5 对话记忆管理
> **文档类型**：领航员
> **锚定决策**：D1（摘要优先+滑动窗口降级）、D2（retrieve→memory→generate 拓扑）、D3（summary 独立 state 字段）、D4（count_tokens_approximately）、D5（max_tokens 在 GraphContext）
> **覆盖的 Task 知识点**：跨决策连锁效应、架构隐含前提、每个决策在什么条件下需重审
> **关联文档**：[锚点① add_messages](task_2.5_anchor_01_add_messages.md) · [锚点② trim_messages](task_2.5_anchor_02_trim_and_count.md) · [锚点③ 降级链路](task_2.5_anchor_03_degradation.md)

# 三个模块的协作契约

## 连锁效应

### 链条 1：D3 → D2 → prompt 层（数据流连锁）

这是最长的连锁链，跨越三个模块。链条的源头是决策 D3："summary 存独立 state 字段"。这个决策辐射到整个 memory 子系统的数据流形态。

**D3 层**：`state["summary"]` 作为一个独立字段而非 AIMessage，意味着它不由 `add_messages` reducer 管理——不是 `messages` 列表的一部分。这个选择产生两个直接约束：

1. summary 不参与 memory 触发条件的门槛计算（`count_tokens_approximately(messages)` 不包括 summary）
2. summary 不会被 `RemoveMessage(id=REMOVE_ALL_MESSAGES)` 清除（因为 reducer 只操作 `messages` 字段）

**D2 层**：`retrieve → memory → generate` 的拓扑决定了 memory 在 generate 之前执行。这个顺序意味着：

1. memory 操作后的 `state` 状态已经被合并，generate 读取的是"已压缩"的 messages + 更新后的 summary
2. 如果 memory 在 retrieve 之前执行（比如 `memory → retrieve → generate`），路由节点读取 messages 时可能发现历史已被压缩——但 route 不依赖历史，所以不影响。但更严重的是：retrieve 不涉及状态更新，放在 memory 之前可以**预压缩** generate 的输入

**Prompt 层**：`build_generate_messages` 读取 `state["summary"]` 后注入为 SystemMessage。这里埋了一个隐蔽的耦合：

```python
# build_generate_messages 中
messages: list[BaseMessage] = []
messages.append(SystemMessage(content=templates["system"]))  # 2a：系统指令
#  ... 摘要在这里插入 ...
messages.extend(chat_history)                                    # 2d：历史
messages.append(HumanMessage(...))                              # 2e：当前轮
```

摘要是 SystemMessage，在 few-shot 之前。chat_history 是纯消息，在 few-shot 之后。这个插入位置的选择看似是 prompt 层的内部细节，实则受 D3 的约束：

- 如果 D3 选择将摘要作为 AIMessage prefix（抛弃的方案），那么摘要会出现在 chat_history 中，插入位置在末尾。prompt 层不需要特殊处理，只需要 LLM 在生成时看到前缀即可。
- D3 选择了独立字段，所以 prompt 层必须有对应的读取逻辑。

**连锁意味什么**：D3 的变更（比如改为用 AIMessage 存储摘要），直接影响 memory 和 prompt 两个模块——memory 节点需要将摘要写入 messages 而非 summary，prompt 层需要从 messages 中提取摘要而非读取 state["summary"]。这三点的变更必须同步。

### 链条 2：id=None → REMOVE_ALL_MESSAGES → 两条路径同一种形态（约束连锁）

这是架构约束对实现的连锁影响。触发点是 LangChain 消息对象的 `id=None` 行为。如锚点①所述，没有显式指定 id 的消息在 reducer 中才被分配 UUID，导致应用层无法通过 `RemoveMessage(id=known_id)` 精确删除。

这个约束迫使两条路径——摘要成功和降级 trim——都使用 `RemoveMessage(id=REMOVE_ALL_MESSAGES)` 作为删除手段：

```python
# 摘要成功路径
return {
    "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *kept],
    "summary": new_summary,
}
# 降级路径
return {
    "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *kept],
}
```

**两条路径在删除语义上完全一致**——都是全量清除旧消息 + 重建保留列表。区别仅在于 `kept` 列表的内容（摘要 vs trim）和是否写入 summary。这意味着：

1. **`kept` 的完整性完全依赖内存逻辑**，reducer 不会帮它补漏。如果 `kept` 漏掉了 SystemMessage，那就是真的丢了——reducer 的 `REMOVE_ALL_MESSAGES` 不做"保留特定类型消息"的特殊处理。这与按 ID 删除的模式不同（按 ID 删除时，没有指定删除的消息自动保留）。

2. **无法实现"选择性保留"**。如果未来需要"保留第 1 轮的 SystemMessage + 删除第 2-5 轮 + 保留第 6 轮"，当前架构不支持。必须迁移到 ID 模式或设计新的删除策略。

3. **文档说明 `REMOVE_ALL_MESSAGES` 在 `add_messages` 中的精确行为**。根据源码，它是预处理短路，不是合并循环中的特殊逻辑。因此不会受 `include_system` 等参数影响——这与 `trim_messages` 的参数独立性不同。

### 链条 3：D5 × D4 × 0.9 margin（精度连锁）

`max_tokens` 在 `GraphContext` 中（D5），`count_tokens_approximately` 估算（D4），0.9 margin 是经验值——三个决策在精度维度上叠加：

```
D5（设定阈值 4000）→ D4（估算值 3800，实际可能 4500）→ 0.9 margin（降到 3420 估算）
```

叠加后，实际触发 memory 的真实 token 数可能是 3420（估算）× 1.5（中文偏差）≈ 5130 实际 token。触发的"实际阈值"与配置的"名义阈值"可能差 28%。

**这不是 bug，而是设计取舍**：精度连锁方向是"更保守"（更早触发），不是"更激进"（更晚触发）。早触发只浪费一些 token，晚触发可能导致上下文溢出。保守方向是正确的。

但如果将来需要更精确的阈值控制（如"务必在 4000 token 时触发"），需要打破这个连锁链——在 memory_node 中增加 `llm.get_num_tokens_from_messages` 的校准步骤。

## 架构隐含前提

### 前提 1：memory 延迟触发的代价是可接受的

即使 `count_tokens_approximately` 低估了 token 数（比如实际 5000 时估算 3800），memory 节点返回 `{}`（无操作），generate 节点的 LLM 调用仍能继续。不会崩溃，只是 LLM 的上下文窗口压力更大。这个假设依赖 LLM 的上下文窗口 > `max_tokens`（通常 8K/16K/128K vs 4K）。

**违背条件**：`max_tokens` 被设置为接近 LLM 上下文窗口（如 7K/8K），误差可能导致实际 token 超出窗口。
**建议的监控指标**：`state["messages"]` 的 `count_tokens_approximately` 与 LLM 返回的 `usage_metadata['total_tokens']` 的比值。比值 > 0.6 且持续增长，说明 memory 触发延迟严重。

### 前提 2：summary 字段不会膨胀到影响生成质量

如锚点③所述，summary 字段没有压缩机制。这个前提成立的条件是：摘要的增长慢到可以忽略。每轮 ~50-150 tokens 增量，在 10-20 轮对话内确实可以忽略。

**违背条件**：对话轮次超过 50 轮且 memory 频繁触发，summary 可能膨胀到 1000+ tokens。
**建议的扩展**：在 `memory_node` 中增加 `len(summary) > max_tokens * 0.5` 检查，触发 secondary summarization。

### 前提 3：trim 降级后 Human-AI 配对充分

`trim_messages` 的 `start_on="human"` + `end_on=("human",)` 保护首尾配对，但不保证中间位置的配对完整。考虑：

```
消息列表：[Sys, Human1, AI1, Human2, AI2, Human3, AI3, Human4]
trim 后可能：[Sys, Human2, AI2, Human3]  # AI2 的配对 Human2 保留
```

但如果 trim 的 token 预算刚好切在 Human2 中间：

```
token 预算刚好包含 [Sys, Human2] 但不包含 AI2
→ start_on 确保第一条非 sys 消息是 Human2 → 保留
→ 但 AI2 被裁掉了
→ Human2 成为孤立 HumanMessage（没有对应的 AI）
```

这是 LLM 输入的常见格式（当前轮本身就是孤立 Human），但它出现在 chat_history 区域就有问题了。`build_generate_messages` 会把它当作历史对话中的一轮——但它是孤立的，LLM 可能困惑"为什么没有人回答这个问题"。

项目测试中通过 `test_no_orphan_ai_message` 验证的是"AI 不孤立"，没有验证"Human 不孤立"。这是当前测试覆盖的一个缺口。在 chat_history 中孤立的 HumanMessage（有问无答）可能导致 LLM 的回答风格偏差。

**违背条件**：trim 预算恰好切在一对 Human-AI 之间，且 Human 被保留而 AI 被裁掉。
**修复方向**：在 `trim_conversation_history` 中添加后处理步骤，检查是否有孤立的 HumanMessage（排除最后一条当前轮），如果有，移除多余的 HumanMessage。

### 前提 4：checkpoint 恢复后 summary 字段值正确

checkpoint 将 `state["summary"]` 作为字符串持久化。恢复时，这个值被反序列化为 str。如果数据库中的 summary 字段为 `NULL`（如某种异常导致写入失败），恢复后 `state["summary"] = None`。

`build_generate_messages` 中 `if summary:` 对 None 的判断为 `False`，摘要被跳过。memory_node 中 `state.get("summary", "")` 对 None 返回 None（不是 ""），`summarize_conversation` 中 `if existing_summary:` 同样跳过。结果：**摘要被静默丢弃**。

**违背条件**：checkpoint 写入了 `NULL` 值（异常场景）或数据库迁移后默认值为 NULL。
**修复方向**：在 `memory_node` 中添加防御性检查：`summary = state.get("summary", "") or ""`。

## 重审条件

以下任一条件满足时，当前架构设计需要重审：

1. **`max_tokens` 被配置到接近 LLM 上下文窗口的 80% 以上**（如 8K 上下文中设 6K）：需要切换到模型特定 tokenizer 以提高精度

2. **消息 ID 在 LangChain 新版本中变为自动分配**：如果 `BaseMessage.__init__` 默认生成 UUID，则 `id=None` 问题消失，可以迁移到按 ID 删除，移除 `REMOVE_ALL_MESSAGES` 的依赖

3. **对话轮次长期超过 50 轮**：summary 膨胀和 trim 精度问题成为实际风险，需要分层摘要或长期记忆机制

4. **LLM 上下文窗口缩小**（如切换模型导致的窗口缩小）：当前 margin 设计的有效性需要重新验证

## 如果没有领航员

读完三篇锚点后：

- 锚点①解释了 `add_messages` 的删除机制和 `REMOVE_ALL_MESSAGES` 的工作方式
- 锚点②解释了 `trim_messages` 的算法细节和 token 估算原理
- 锚点③解释了降级路径的边界和隐含前提

但读完全部三篇，你仍然不知道这些机制在实际的记忆管理流程中**如何协同工作**：

- 摘要成功时，`kept` 列表经过 `RemoveMessage(REMOVE_ALL)` → `add_messages` reducer → state merge → generate_node 读取，这条路径上每个环节的假设是什么？
- `count_tokens_approximately` 的误差在估算中使用（无操作判断）、在降级中使用（0.9 margin）、在 generate 中也使用（LLM 自己的 tokenizer）——三个使用点对精度的需求不同，但当前共享一个估算器
- REMOVE_ALL_MESSAGES + kept 的形态被 id=None 约束强制统一，但两条路径（摘要 vs trim）对这个形态的正确性依赖完全相同——`kept` 漏掉消息时两条路径都崩溃

这些是领航员覆盖的"跨决策拼图"。
