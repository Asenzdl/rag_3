> **关联 Task**：Task 2.5 对话记忆管理
> **文档类型**：锚点
> **锚定决策**：D1（摘要优先+滑动窗口降级）、D4（`count_tokens_approximately`）
> **覆盖的 Task 知识点**：`trim_messages` 四种 strategy 对比、`start_on`/`end_on` 与 `include_system` 的执行时序、`count_tokens_approximately` 的估算算法与中文误差边界、Human-AI 配对被破坏的条件与修复策略、降级阈值 0.9 margin 的工程设计逻辑
> **关联文档**：[领航员](task_2.5_navigator.md) · [锚点① add_messages](task_2.5_anchor_01_add_messages.md) · [锚点③ 降级链路](task_2.5_anchor_03_degradation.md)

# `trim_messages` 滑动窗口与 `count_tokens_approximately`

## 反转+二分：一个反直觉的实现

如果被问到"`trim_messages(strategy="last")` 如何从消息列表中保留最后 N 个 token 的消息"，直觉回答可能是"从末尾开始遍历，累积 token 直到达到阈值，找到切割点后返回"。

但实际实现走的是一条完全不同的路径。

`trim_messages` 的 `strategy="last"` 最终调用 `_last_max_tokens` 函数。它的核心逻辑在第 2057 行：

```python
# Reverse messages to use _first_max_tokens with reversed logic
reversed_messages = messages[::-1]

reversed_result = _first_max_tokens(
    reversed_messages,
    max_tokens=remaining_tokens,
    token_counter=token_counter,
    text_splitter=text_splitter,
    partial_strategy="last" if allow_partial else None,
    end_on=start_on,
)

# Re-reverse the messages and add back the system message if needed
result = reversed_result[::-1]
```

**将消息列表反转后使用 `_first_max_tokens`**，而不是写一个专门的 `_last_max_tokens` 实现。`_first_max_tokens` 内部用二分搜索找到在 token 预算内的最大前缀长度。

这意味着滑动窗口裁剪的算法路径是：

1. **预处理**：`end_on` 过滤、`include_system` 提取、反转
2. **核心计算**：二分搜索（`_first_max_tokens` 对反转后的列表）
3. **后处理**：再反转、重贴 SystemMessage

为什么这样设计？两个原因：

**原因 1：复用二分搜索逻辑**。`_first_max_tokens` 用二分搜索在 O(log n) 时间内找到最大可接受前缀，而不是线性遍历。反转后"找最后几条"变成了"找前几条"，可直接复用。如果单独写 `_last_max_tokens`，要么也用二分（搜索空间是"从后往前第 k 条"），要么线性遍历（O(n)）。既然二分已经实现，复用是最经济的。

**原因 2：`end_on` 的语义在反转后被复用为 `start_on`**。在原始列表中 `end_on=("human",)` 要求"最后一条必须是 HumanMessage"，反转后变成了"第一条必须是 HumanMessage"，正好是 `_first_max_tokens` 的 `end_on` 参数语义。参数名的复用是对称性设计的体现。

## 算法步骤逐层拆解

以项目调用为例：

```python
trim_conversation_history(
    messages,
    max_tokens=int(max_tokens * 0.9)  # 降级时用 0.9 margin
)
```

内部展开为：

```python
trim_messages(
    messages,
    max_tokens=max_tokens,
    token_counter=count_tokens_approximately,
    strategy="last",
    start_on="human",
    end_on=("human",),
    include_system=True,
)
```

### 第 1 步：`end_on` 预过滤

```python
if end_on:
    for _ in range(len(messages)):
        if not _is_message_type(messages[-1], end_on):
            messages.pop()
        else:
            break
```

从末尾开始，**移除所有不是指定类型的消息**，直到遇到第一个匹配类型的消息。

`end_on=("human",)` 意味着：如果消息列表以 AIMessage 结尾，这个 AIMessage 会被移除。无论 token 预算是否充足，最后一条消息**必须**是 HumanMessage。

这就是为什么 `test_below_threshold` 中原先断言 `len(result) == len(messages)` 失败——即使消息总数远低于 token 阈值，`end_on` 仍然会移除末尾孤立的 AIMessage。

`_is_message_type` 的实现：

```python
def _is_message_type(message, type_):
    types = [type_] if isinstance(type_, (str, type)) else type_
    types_str = [t for t in types if isinstance(t, str)]
    types_types = tuple(t for t in types if isinstance(t, type))
    return message.type in types_str or isinstance(message, types_types)
```

支持字符串名（`"human"`）和类名（`HumanMessage`）两种匹配方式。

### 第 2 步：SystemMessage 提取

```python
system_message = None
if include_system and len(messages) > 0 and isinstance(messages[0], SystemMessage):
    system_message = messages[0]
    messages = messages[1:]
```

只有 `messages[0]` 是 SystemMessage 时才提取，否则什么都不做。提取后从 `max_tokens` 中扣除 SystemMessage 的 token 数，确保裁剪后的消息 + SystemMessage 不超过 `max_tokens`。

这隐含了一个约束：SystemMessage **必须在索引 0**。如果 SystemMessage 被插入到消息列表的其他位置，`include_system` 不会识别它。

### 第 3 步：反转 + 二分搜索

反转后调用 `_first_max_tokens`，内部使用二分搜索：

```python
left, right = 0, len(messages)
max_iterations = len(messages).bit_length()
for _ in range(max_iterations):
    if left >= right:
        break
    mid = (left + right + 1) // 2
    if token_counter(messages[:mid]) <= max_tokens:
        left = mid
    else:
        right = mid - 1
```

`max_iterations = len(messages).bit_length()` 确保在 `O(log n)` 内收敛——对 1000 条消息只需要约 10 次迭代，每次调用一次 `token_counter`。

二分搜索的终止条件：找到最大的 `mid` 使得 `messages[:mid]` 的总 token ≤ `max_tokens`。

### 第 4 步：可选的部分消息保留

如果 `allow_partial=True` 且二分搜索后还有 token 余量，会尝试从被截断的第一条消息中提取部分内容。具体做法：

1. 如果消息含有结构化内容（`content` 是列表），从最内层块开始逐块追加
2. 如果消息是纯文本，用 `text_splitter`（默认按换行符拆分）分割，按份追加

本项目设置 `allow_partial=False`，所以如果消息超了阈值，整条被裁掉。这符合"牺牲精度保完整性"的设计——宁可少保留一条，也不让 LLM 看到半条消息。

### 第 5 步：反转后还原

`reversed_result[::-1]` 回到原始顺序，然后 `if system_message: result = [system_message, *result]` 将 SystemMessage 放回开头。

## `start_on` 与 `end_on` 的配对完整性保证

`trim_messages` 的参数设计确保了 Human-AI 配对的完整性。项目配置 `start_on="human"` + `end_on=("human",)`，两条防线：

### `end_on`（后防线）

在步骤 1 执行，确保**结果列表的最后一条**是 HumanMessage。这意味着如果原始列表以 AIMessage 结尾，该 AIMessage 被移除。但注意：`end_on` 只检查最后一条的类型，不检查配对完整性。如果列表中有 `[Human1, AI1, Human2]`（AI2 已被 `end_on` 移除），`[Human1, AI1, Human2]` 中 Human2 没有对应的 AI——这种"孤立的 HumanMessage"不会被检测到，因为 LLM 输入中当前问题本就是孤立的 HumanMessage。

### `start_on`（前防线）

在步骤 3 内部（通过反转后的 `end_on` 参数），确保**结果列表的第一条**（排除 SystemMessage 后）是 HumanMessage。这意味着如果裁剪后剩下的第一条消息是 AIMessage（即缺失对应的 HumanMessage），该 AIMessage 会被移除。

两条防线配合，保证裁剪结果中："第一条业务消息是 Human，最后一条业务消息也是 Human，中间的 Human-AI 对完整"。

但有一个边界：如果裁剪结果中某个 AIMessage 被截断而其对应的 HumanMessage 被保留（或反之），配对仍然可能被破坏。`trim_messages` 不解决这个问题——它的保护范围是首尾消息类型，不是配对完整性。这就是为什么项目在 `test_no_orphan_ai_message` 中手动遍历验证配对完整性，而不是依赖 `trim_messages` 的参数保证。

### `include_system` 的特殊性

`include_system=True` 时，SystemMessage 从步骤 1 预过滤和步骤 3 的 token 计算中被完全隔离。这意味着：

1. SystemMessage 不计入 `max_tokens` 预算
2. SystemMessage 在所有裁剪之后被重新插入到结果列表头部
3. SystemMessage 不受 `start_on`/`end_on` 约束

这隐含了一个设计决策：SystemMessage 的 token 消耗是"固定损耗"，不参与滑动窗口竞争。在长对话中，SystemMessage + SummaryMessage 可能本身就已经接近模型的上下文窗口，但 `trim_messages` 不会对此做保护。

## `count_tokens_approximately` 估算算法

与 `trim_messages` 配套使用的 token 计数器是 `count_tokens_approximately`。它在 `langchain_core/messages/utils.py` 第 2186 行定义，添加于 `langchain-core 0.3.46`。

### 核心算法

```python
def count_tokens_approximately(
    messages: Iterable[MessageLikeRepresentation],
    *,
    chars_per_token: float = 4.0,
    extra_tokens_per_message: float = 3.0,
    count_name: bool = True,
    tokens_per_image: int = 85,
) -> int:
```

计算方法极其直接：

```
token_count = Σ ceil(单个消息字符数 / chars_per_token) + extra_tokens_per_message
```

对于每条消息，计入的字符包括：

| 信息来源 | 计入内容 |
|---------|---------|
| content（字符串） | `len(content)` |
| content（列表） | 逐块处理：text 块计入 `len(text)`，image 块计入固定 85 token，未知块计入 `len(repr(block))` |
| role | `len(_get_message_openai_role(message))` 如 `"user"`、`"assistant"` |
| name | `len(message.name)`（如果 `count_name=True`） |
| AI tool_calls | `repr(message.tool_calls)` |
| ToolMessage | `len(message.tool_call_id)` |

然后累加每个 `ceil(message_chars / 4.0)`，再加 `3.0`。

### 中文误差分析

`chars_per_token=4.0` 这个默认值来自 OpenAI 的估算公式："1 token ≈ 4 characters in English"。但这条规律对中文不成立：

- 英文：1 token ≈ 3-4 字符（"LangGraph is a framework" ≈ 22 字符 ≈ 6 tokens）
- 中文：1 token ≈ 1.5-2 字符（"LangGraph 是一个框架" ≈ 12 字符 ≈ 7-8 tokens）
- 中文 vs 英文：同等字符数下，中文 token 数是英文的 **2 倍左右**

这意味着 `count_tokens_approximately` 对中文为主的对话会**显著低估**实际 token 数。如果阈值设为 4000，实际 token 数可能是 6000+。

项目中的影响：memory_node 的触发条件 `total <= max_tokens` 可能对中文对话"延迟触发"。一条实际已超过 4000 token 的中文消息列表，估算值可能仍在 4000 以下，memory_node 返回 `{}`（无操作）。

### `use_usage_metadata_scaling` 校准机制

在 `langchain-core 0.3.46` 中新增了一个校准参数 `use_usage_metadata_scaling`。它的思路是：如果 AI 消息中携带了 `usage_metadata['total_tokens']`（从 LLM 返回的 API 响应中获取），可以用它来估算"实际 token 数 / 估算 token 数"的比例因子，然后用这个因子校准后续估算：

```python
if use_usage_metadata_scaling and ...:
    scale_factor = last_ai_total_tokens / approx_at_last_ai
    token_count *= min(1.25, max(1.0, scale_factor))
```

比例因子被钳位在 `[1.0, 1.25]` 之间。这意味着最多修正 25% 的上调，不下调。对于中文场景，1.25 的上限仍可能不足（实际需要 ~2.0 的比例），但至少比完全不校准好。

项目中未启用此特性，原因是依赖 `usage_metadata` 的可用性——如果 LLM 不返回 token 用量信息（如某些本地模型），校准不会触发。为了保持实现的一致性，项目选择了统一的估算策略。

### 为什么不使用模型特定 tokenizer

使用 `llm.get_num_tokens_from_messages()` 可以获得精确计数，但代价是：

1. **内存占用**：每次调用都需要模型 tokenizer 加载到内存
2. **延迟**：每次 token 计数都是一次函数调用（涉及 tokenizer 的编码操作）
3. **模型绑定**：更换 LLM 后 tokenizer 不同，计数结果可能不一致
4. **可用性**：memory_node 需要自己的 LLM 实例来调用 tokenizer，与生成节点共享 LLM 实例（`llm`），但摘要也需要调用 `llm.invoke`——同一个 LLM 实例在 memory_node 中被两个不同目的使用。如果改用专门的 tokenizer LLM，需要额外创建实例。

框架文档明确推荐："`count_tokens_approximately` is recommended for using `trim_messages` on the hot path, where exact token counting is not necessary。"Token 计数本身不需要高精度——阈值判断是"大约超了就触发"，不是"精确到个位数的预算分配"。近似计数足够。

## 面试要点

1. **`trim_messages` 的实现复用二分搜索**：`strategy="last"` 不是从后向前遍历，而是反转后用 `_first_max_tokens`（二分搜索）。这个反直觉的设计是为了代码复用。

2. **执行顺序影响语义**：`end_on` 在 trim 之前执行（预过滤），`start_on` 在 trim 之后执行（通过反转后的 `end_on`）。`include_system` 最特殊——完全隔离 SystemMessage，不计入 token 预算。

3. **中文 token 误差**：默认 `chars_per_token=4.0` 对中文低估约 2 倍。项目中实际触发阈值可能是预期的 2 倍。`use_usage_metadata_scaling` 可部分校准但有 1.25 倍上限。

4. **配对被破坏的边界**：`start_on`+`end_on` 保护首尾消息类型，但不保护中间位置的配对。Human 截断而 AI 保留（或反之）仍然可能发生。深度测试需要手动验证配对完整性。

5. **近似 vs 精确计数的取舍**：框架官方推荐的 `count_tokens_approximately` 在"是否触发"的二元判断上足够准确——200 的误差不影响是否触发 4000 阈值的判断。但如果是"预算分配"场景（如窗口精确切分），模型特定 tokenizer 是必要的。
