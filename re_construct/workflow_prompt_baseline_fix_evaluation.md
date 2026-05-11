# Workflow Prompt 基底偏差修正评估

## 1. 背景

Task 2.5（对话记忆管理）设计中发现了当前 Workflow 路径的 prompt 体系与 LangGraph 官方模式之间的基底偏差。

### 偏差本质

```text
LangGraph 官方模式：
  state["messages"] → trim/summarize → llm.invoke(messages)

当前 Workflow 模式：
  state["messages"] → memory 节点 → state["messages"]
                                        ↓
  prompt.invoke({context, question, chat_history ← })
```

官方模式中 messages 是 LLM 输入的唯一载体，记忆管理直接操作 messages。当前模式中 messages、context、question、chat_history 被拆分到不同变量中，导致记忆管理的输出需要通过 chat_history 桥接层才能进入 LLM。

### 技术债务时间线

```text
Task 1.6 (RAGChain 诞生)：  LCEL prompt {context}+{question}         → 合理，无图
Task 2.1 (状态定义)：        messages + question 双字段                  → 开始偏离
Task 2.2 (生成节点)：         沿用 LCEL prompt，messages 不参与 prompt   → 偏离固化
Task 2.5 (记忆管理)：        发现 messages 与 prompt 输入断裂             → 暴露矛盾
```

关键决策点在 Task 2.2：generate_node 本应以 state["messages"] 为主要输入，但沿用了 RAGChain 的 LCEL prompt 体系。

---

## 2. 当前架构分析

### 2.1 双轨制

当前项目存在两套互不干扰的生成路径：

| 路径 | 使用者 | Prompt 机制 | 调用方式 |
|------|--------|------------|---------|
| **RAGChain** | `app.py`（CLI 交互） | LCEL chain: `prompt \| llm \| StrOutputParser` | `{"context": ..., "question": ...}` |
| **Workflow** | `builder.py`（LangGraph 图） | LCEL chain: `prompt \| llm` | `{"context": ..., "question": ...}` |

两者都使用相同的 LCEL chain，但 RAGChain 是独立于 Workflow 的旧路径。本次修正只影响 Workflow 路径。

### 2.2 Workflow 生成节点当前数据流

```text
state["question"] ──────────────────┐
state["documents"] → format_docs → context┬─→ {"context": context, "question": question} → prompt | llm → AIMessage
state["messages"] → （只存检查点，不参与 prompt）
```

问题：messages 不参与 LLM 输入，记忆管理对它做的任何操作都不影响生成质量。

### 2.3 约束优先级回顾

```text
第 0 层（用户画像）：学习生产级设计，与大厂面试对齐
第 1 层（质量准则）：模块分离、单一职责
第 2 层（Task 指令）：LCEL prompt、context/question 变量

第 1 层 修正第 2 层：generate_node 应以 messages 为核心
```

---

## 3. 修正方案

### 3.1 核心改动

generate_node **不再使用 `prompt | llm` LCEL 链**，改为**直接组装 messages 列表**后调用 `llm.invoke(messages)`。

```text
修正前：
  retryable_invoke({"context": context, "question": question})
  # 实际调用：prompt | llm → AIMessage

修正后：
  assembled = [
    SystemMessage(system_instruction),
    *chat_history,        # memory 节点处理过的 messages
    HumanMessage(context + question),
  ]
  ai_message = llm.invoke(assembled)
  # 直接调用 llm，不走 prompt chain
```

### 3.2 影响范围

#### 需修改的源码（3 个文件）

**`src/workflow/nodes.py`**（~50 行，核心修改）

| 改动项 | 当前 | 修正后 |
|--------|------|--------|
| `create_workflow_nodes` 签名 | `(retriever, llm, prompt, citation_extractor, max_iterations)` | `(retriever, llm, citation_extractor, max_iterations)` — 移除 `prompt` 参数 |
| 生成链 | `prompt_llm_chain = prompt \| llm` | 删除，不再需要 |
| 重试函数 | `retryable_invoke = with_retry(prompt_llm_chain.invoke)` | `retryable_invoke = with_retry(lambda msgs: llm.invoke(msgs))` |
| generate 调用 | `retryable_invoke({"context": context, "question": question})` | `retryable_invoke(assembled_messages)` |
| 新方法 | — | `_assemble_messages(state, context)`: 组装 System + chat_history + Human |

**`src/workflow/builder.py`**（~5 行）

| 改动项 | 当前 | 修正后 |
|--------|------|--------|
| create_workflow_nodes 传参 | `nodes = create_workflow_nodes(retriever, llm, prompt, ...)` | `nodes = create_workflow_nodes(retriever, llm, ...)` — 不再传 prompt |
| get_prompt 调用 | `prompt = get_prompt(PromptVersion.V2, include_few_shot=True)` | 可移除（如果 Workflow 不再需要 prompt），或保留供其他用途 |

**`src/generation/prompts.py`**（~10 行新增）

| 改动项 | 当前 | 修正后 |
|--------|------|--------|
| 公共 API | `get_prompt()` → 返回 ChatPromptTemplate | 新增 `get_system_template(version)` → 返回 str，供 generate_node 组装 messages |

#### 需修改的测试（2 个文件）

**`tests/test_workflow_nodes.py`**（~100 行）

| 测试项 | 改动原因 |
|--------|---------|
| `test_factory_returns_three_nodes` | `create_workflow_nodes` 签名变化 |
| `TestGenerateNode` 全部测试 | fixture 不再需要 `mock_prompt`；mock 方式从 mock LCEL chain 改为 mock `llm.invoke` |
| 协作测试 | `state_with_documents` fixture 可能有调整 |

**`tests/test_workflow_builder.py`**（~10 行）

| 测试项 | 改动原因 |
|--------|---------|
| `_build_graph_with_mocks` | 不再需要 `patch("get_prompt")` |

#### 不受影响的文件

| 文件 | 原因 |
|------|------|
| `src/generation/rag_chain.py` | RAGChain 继续使用 LCEL chain，Workflow 路径独立修改 |
| `src/app.py` | 使用 RAGChain，不涉及 Workflow |
| `src/workflow/state.py` | `question` 字段仍被 route_node 使用 |
| `tests/test_prompts.py` | Prompt 模板独立测试不受影响 |

### 3.3 修正后的数据流

```text
修正前（Task 2.5 需强加 chat_history）：

  state["documents"] → format_docs → context ──────────────────────────────┐
  state["messages"] → memory 节点 → messages → extract chat_history → ─┐   │
                                                                        ↓   ↓
                                                    prompt.invoke({context, question, chat_history})

修正后（messages 是 LLM 输入唯一载体）：

  state["documents"] → format_docs → context ─────┐
                                                    ↓
  state["messages"] → memory 节点 → messages → assemble → llm.invoke(assembled)
  prompts.py → get_system_template() → system ────┘
```

---

## 4. 收益与成本

### 4.1 收益

1. **与 LangGraph 官方模式对齐** — memory 节点直接操作 messages，可直接使用 `SummarizationNode`、`trim_messages`、`RemoveMessage` 等官方工具
2. **generate_node 职责内聚** — 输入和输出都是 messages，无需关心 context/question 的分拆
3. **测试简化** — mock `llm.invoke(msgs)` 比 mock `prompt | llm` chain 更直接
4. **面试自洽** — generate_node 的设计可以在面试中直接引用 LangGraph 官方模式
5. **Task 2.5 实现自然** — 不需要 chat_history 桥接层，memory 节点处理后的 messages 直接流入 LLM

### 4.2 成本

1. **修改范围涉及 5 个文件，~170 行代码调整**
2. **两套生成路径并行维护** — RAGChain（LCEL）和 Workflow（直接调 llm）各自独立
3. **prompts.py 角色降级** — 从 LCEL chain 的数据源降级为纯字符串来源

### 4.3 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| RAGChain 路径被误改导致 CLI 中断 | 低 | RAGChain 完全不碰 |
| 新消息组装顺序出错导致 LLM 质量下降 | 中 | 测试验证消息顺序 |
| few-shot 示例丢失 | 中 | generate_node 组装时手动插入 few-shot 消息 |
| prompt 模板维护成本上升 | 中 | `prompts.py` 保留模板字符串 + 新增 `get_system_template()` |

---

## 5. 与 Task 2.5 的衔接

### 修正后的 Task 2.5 数据流

```text
memory 节点（新增）：
  state["messages"] → trim_messages / summarize_conversation → RemoveMessage + 摘要 → 写回 state["messages"]

generate 节点（修正后）：
  state["messages"]（memory 已处理）+ documents → assemble → llm.invoke()

图拓扑变更：
  retrieve → [memory] → generate
```

### 不修基底的替代集成路径

如果不做基底修正，Task 2.5 的集成方案：

```text
memory 节点（新增）：
  state["messages"] → trim_messages / summarize_conversation → RemoveMessage + 摘要 → 写回 state["messages"]

generate 节点（现有 LCEL chain + 新增 chat_history）：
  builder 启用 include_chat_history=True
  generate_node 从 state["messages"] 提取 chat_history → 传入 prompt

图拓扑变更：
  retrieve → [memory] → generate
```

### 路径对比

| 维度 | 修复基底 + memory | 保留基底 + memory + chat_history |
|------|------------------|--------------------------------|
| 改动范围 | 5 个文件 ~170 行 | 3 个文件 ~50 行 |
| 与官方模式对齐 | 完全对齐 | 不对齐 |
| 记忆管理层数 | 1 层（messages 直接输入） | 2 层（chat_history 桥接） |
| 面试自洽性 | 高 | 中（需解释为何 context/question 独立） |
| 测试改动 | 大 | 小 |
| 风险等级 | 中 | 低 |

---

## 6. 决策建议

如果 **Task 2.2-2.4 的 Workflow 代码已稳定且通过测试（当前状态为是）**，且**预期 Phase 3-5 中 Workflow 路径仍会继续演进（是）**，则建议修正基底。偏差暴露在早期（Phase 2 的 Task 2.5），修正成本最低；越往后累积的代码越多，修正成本越高。
