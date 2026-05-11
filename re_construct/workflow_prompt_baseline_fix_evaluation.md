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

## 3. 修正方案的设计误区

### 3.1 初步设计（有问题的版本）

generate_node **不再使用 `prompt | llm` LCEL 链**，改为**直接组装 messages 列表**后调用 `llm.invoke(messages)`。

```text
修正前：
  prompt_llm_chain = prompt | llm
  retryable_invoke = with_retry(prompt_llm_chain.invoke)
  ai_message = retryable_invoke({"context": context, "question": question})

修正后：
  retryable_invoke = with_retry(lambda msgs: llm.invoke(msgs))
  assembled = [
    SystemMessage(system_instruction),     # ← 模板字符串从哪来？
    *chat_history,                          # memory 节点处理过的 messages
    HumanMessage(f"参考文档：{context}\n\n问题：{question}\n\n..."),  # ← 格式在 nodes.py 中硬编码？
  ]
  ai_message = retryable_invoke(assembled)
```

### 3.2 三个技术陷阱

**陷阱 1：HumanMessage 模板格式化逻辑泄漏**

当前 human template（V2）包含关键格式指令：
```
参考文档：
{context}

问题：{question}

请基于以上参考文档回答问题，使用 [1], [2] 等标记引用，并在末尾列出来源。
```

如果 generate_node 直接拼装 `f"参考文档：\n{context}\n\n..."`，意味着：
- 模板格式化逻辑从 `prompts.py` 泄漏到 `nodes.py`
- 修改提示措辞需要在两处同步改
- `HUMAN_TEMPLATE_V2` 成为死代码（只在 RAGChain 中用，Workflow 不用）

**陷阱 2：System template 和 few-shot 获取路径断裂**

修正后 generate_node 需要：
```python
from src.generation.prompts import FEW_SHOT_EXAMPLES  # 导入内部常量
from src.generation.prompts import SYSTEM_TEMPLATE_V2  # 导入内部常量
```

但 `prompts.py` 的公共 API 只暴露 `get_prompt()`（返回 ChatPromptTemplate），不暴露纯字符串级别的接口。修正后 generate_node 需要绕开公共 API 直接取内部常量。

**陷阱 3：Prompt 版本管理断裂**

当前 builder.py 中版本选择清晰：
```python
prompt = get_prompt(PromptVersion.V2, include_few_shot=True)
```

修正后 builder 不再传 prompt。`PromptVersion` 的选择权谁来继承？
- 让 builder 传 version 参数到 `create_workflow_nodes`？
- 还是 generate_node 固定用 V2？

### 3.3 三个陷阱的根因

修正方案的设计思维是"generate_node 不再使用 prompt"。但 prompt 的真正职责不是 LCEL chain，而是**提供 system 指令和 human message 的格式化模板**。去掉 LCEL chain 是正确的，但模板获取的职责不能丢——它不是去掉了 prompt，而是把 prompt 知识散落到 nodes.py 中了。

### 3.4 更干净的修正方式：职责不动，去掉 LCEL 中间层

让 `src/workflow/prompts.py` 提供**构建消息列表的纯函数**，而不是让 `generate_node` 自己拼装：

```python
# src/workflow/prompts.py — 替代原 LCEL chain 的 messages 构建
def build_generate_messages(
    *,
    context: str,
    question: str,
    chat_history: Iterable[BaseMessage],
    version: PromptVersion = PromptVersion.V2,
    include_few_shot: bool = True,
) -> list[BaseMessage]:
    """构建生成节点的 LLM 输入消息列表。

    替代原 prompt | llm chain，将 template 知识保留在 prompts.py 中。
    """
    templates = PROMPT_REGISTRY[version]
    messages: list[BaseMessage] = [SystemMessage(content=templates["system"])]

    if include_few_shot and version == PromptVersion.V2:
        for h, a in FEW_SHOT_EXAMPLES:
            messages.append(h)
            messages.append(a)

    messages.extend(chat_history)
    messages.append(HumanMessage(
        content=templates["human"].format(context=context, question=question)
    ))
    return messages
```

修正对象不是"去 prompt"，而是**去掉 LCEL chain 这个中间层**：

```text
修正前（LCEL chain）：
  prompt = get_prompt(V2, include_few_shot=True)
  prompt_llm_chain = prompt | llm
  ai_message = prompt_llm_chain.invoke({"context": ..., "question": ...})
                                   ↓
修正后（纯函数 build，在 src/workflow/prompts.py 中）：
  messages = build_generate_messages(context=..., question=..., chat_history=[...])
  ai_message = llm.invoke(messages)
```

这样：
- 模板知识集中在 `src/workflow/prompts.py`（workflow 自有）和 `src/generation/prompts.py`（RAGChain 自有），两者独立演进
- `generate_node` 只调一个函数，不碰模板格式
- `RAGChain` 和 `Workflow` 不再共享 prompt 模板，两者彻底解耦
- 版本管理、few-shot 逻辑在 `src/workflow/prompts.py` 内部管理
- 空检索拦截逻辑不变（generate_node 第 2 步的 `if not documents` 依然在 LLM 调用前）

---

## 4. 影响范围（基于修正后的方案）

### 4.1 需新增的文件（3 个）

**`src/workflow/prompts.py`**（NEW，~80 行）

| 内容项 | 来源 |
|--------|------|
| Prompt 模板字符串（V1/V2 system + human） | 从 `src/generation/prompts.py` 副本迁移 |
| `FEW_SHOT_EXAMPLES` | 从 `src/generation/prompts.py` 副本迁移 |
| `build_generate_messages()` | 新建，workflow 自有 |
| `format_docs` 导入 | 从 `src/utils/format.py` 导入 |

Workflow 持有自有模板副本，与 RAGChain 完全解耦。初始字符串相同，后续可独立演进。

**`src/utils/format.py`**（NEW，~50 行搬迁）

| 改动项 | 说明 |
|--------|------|
| `format_docs()` | 从 `rag_chain.py` 搬迁至此。纯字符串格式化，不依赖任何模块 |
| 设计理由 | 两路径共享的纯函数，放在 `src/utils/` 中立位置。与 prompt 模板的连锁变化由测试保障 |

**`src/utils/citation.py`**（NEW，~400 行搬迁）

| 改动项 | 说明 |
|--------|------|
| `CitationExtractor` 类 | 从 `src/generation/citation_chain.py` 搬迁至此 |
| `CitationExtractionError` | 从 `src/generation/exceptions.py` 搬迁至此 |
| `Citation`, `ValidatedCitation`, `CitationItem`, `CitationList` | 随 extractor 搬迁 |

### 4.2 需修改的源码（5 个文件）

**`src/workflow/nodes.py`**（~35 行修改）

| 改动项 | 当前 | 修正后 |
|--------|------|--------|
| `create_workflow_nodes` 签名 | `(retriever, llm, prompt, citation_extractor, max_iterations)` | `(retriever, llm, citation_extractor, max_iterations)` — 移除 `prompt` 参数 |
| 生成链 | `prompt_llm_chain = prompt \| llm` | 删除，不再需要 |
| 重试函数 | `retryable_invoke = with_retry(prompt_llm_chain.invoke)` | `retryable_invoke = with_retry(lambda msgs: llm.invoke(msgs))` |
| generate 调用 | `retryable_invoke({"context": context, "question": question})` | `messages = build_generate_messages(...)` 然后 `retryable_invoke(messages)` |
| 导入 `format_docs` | `from src.generation.rag_chain import format_docs` | 删除 |
| 导入 `CitationExtractor` | `from src.generation.citation_chain import CitationExtractor` | `from src.utils.citation import CitationExtractor` |
| 导入 `CitationExtractionError` | `from src.generation.exceptions import CitationExtractionError` | `from src.utils.citation import CitationExtractionError` |
| 导入 PromptVersion/get_prompt | 无（已由 builder 管理） | 无变化 |
| 新增导入 | — | `from src.workflow.prompts import build_generate_messages` |
| 新增导入 | — | `from src.utils.format import format_docs` |

**`src/workflow/builder.py`**（~5 行移除）

| 改动项 | 当前 | 修正后 |
|--------|------|--------|
| 导入 | `from src.generation.prompts import PromptVersion, get_prompt` | 删除此行 |
| prompt 获取 | `prompt = get_prompt(PromptVersion.V2, include_few_shot=True)` | 删除 |
| `create_workflow_nodes` 传参 | `nodes = create_workflow_nodes(retriever, llm, prompt, ...)` | `nodes = create_workflow_nodes(retriever, llm, ...)` |

**`src/generation/rag_chain.py`**（~8 行修改）

| 改动项 | 当前 | 修正后 |
|--------|------|--------|
| `format_docs` 定义 | 在第 73 行的函数定义 | 删除。改为 `from src.utils.format import format_docs` |
| `__all__` 中 `format_docs` | 在 `__all__` 列表中 | 不变（通过导入仍在模块命名空间中，外部 `from src.generation.rag_chain import format_docs` 继续生效） |

**`src/generation/citation_chain.py`**（~5 行修改）

| 改动项 | 当前 | 修正后 |
|--------|------|--------|
| 导入 | `from .exceptions import CitationExtractionError` | `from src.utils.citation import CitationExtractor, CitationExtractionError` |
| `CitationExtractor` 定义 | 在本文件中定义（~300 行） | 删除。改为从 `src.utils.citation` 导入并 re-export |
| 数据类 `Citation`, `ValidatedCitation` | 在本文件中定义 | 删除。从 `src.utils.citation` 导入并 re-export |

**`src/generation/exceptions.py`**（~3 行修改）

| 改动项 | 当前 | 修正后 |
|--------|------|--------|
| `CitationExtractionError` | 在本文件中定义（~20 行） | 删除定义。改为 `from src.utils.citation import CitationExtractionError` |
| `__all__` 中 `CitationExtractionError` | 在列表中 | 不变（通过导入仍在模块命名空间中） |

### 4.3 不受影响的文件

| 文件 | 原因 |
|------|------|
| `src/generation/prompts.py` | RAGChain 自有模板，完全不动 |
| `src/app.py` | 使用 RAGChain，不涉及 Workflow |
| `src/workflow/state.py` | 字段不变（question/documents 仍被 route_node/generate_node 使用） |
| `src/workflow/edges.py` | 条件边路由函数不变 |
| `src/workflow/routing.py` | 意图分类逻辑不变 |
| `src/core/` | 所有工厂/配置/异常基类不受影响 |

### 4.4 修正后的数据流

```text
修正前（workflow 路径）：

  state["messages"] →（只存检查点，不参与 prompt）
  state["documents"] → format_docs → context ────────┐
  state["question"] ──────────────────────────────────┤
                                                      ↓
                           prompt(invoke) →┌─ LCEL chain ─┐
                           context+question │prompt | llm │→ AIMessage
                                            └──────────────┘

修正后（workflow 路径，零 generation 依赖）：

  state["messages"][:-1] ─────────→ chat_history ──┐
  state["documents"] → format_docs → context ──────┤
  state["question"] ────────────────────────────────┤
                                                    ↓
                          src/workflow/prompts.py ─→ build_generate_messages() → llm.invoke(messages)
                          src/utils/format.py ─────→ format_docs()
                          src/utils/citation.py ───→ CitationExtractor
```

### 4.5 模块依赖关系对比

```text
修正前：

  src/workflow/nodes.py ───────────────→ src/generation/rag_chain.py      (format_docs)
  src/workflow/nodes.py ───────────────→ src/generation/citation_chain.py  (CitationExtractor)
  src/workflow/nodes.py ───────────────→ src/generation/exceptions.py      (CitationExtractionError)
  src/workflow/builder.py ────────────→ src/generation/prompts.py          (get_prompt, PromptVersion)

修正后（零耦合）：

  src/workflow/prompts.py (NEW) ── 自有模板 + build_generate_messages
  src/workflow/nodes.py ─────────→ src/utils/citation.py (NEW)
  src/workflow/nodes.py ─────────→ src/utils/format.py (NEW)
  src/workflow/builder.py ─────── 无 generation 导入

  src/generation/citation_chain.py ─→ src/utils/citation.py (re-export)
  src/generation/exceptions.py ─────→ src/utils/citation.py (re-export)
  src/generation/rag_chain.py ──────→ src/utils/format.py (re-export)
```

---

## 5. 深度审查补充发现

### 5.1 format_docs 的归属问题

`format_docs` 当前在 `rag_chain.py` 中定义，两路径都从同一位置导入。这意味着 Workflow 路径在模块层面依赖了 RAGChain 的宿主文件。

**判断理由**：`format_docs` 的输出格式（`[1] content (source: URL)`）与 prompt template 中的引用指令（`请使用 [1], [2] 标记引用`）**连锁变化**。最初计划放在 `prompts.py` 中（与 prompt 模板同文件），但解耦后 Workflow 持有自有模板（`src/workflow/prompts.py`），而 RAGChain 保留原有模板（`src/generation/prompts.py`）——format_docs 是两路径共享的纯函数，放在哪一方的 prompts.py 都会引入交叉依赖。

**决策**：`format_docs` 搬迁到 `src/utils/format.py`（中立位置），`rag_chain.py` 改为从 `src.utils.format` 导入并 re-export。Workflow 从 `src.utils.format` 导入。连锁变化的风险由单元测试覆盖（format_docs 的输出格式是明确的测试契约）。

### 5.2 memory 节点的设计契约

memory 节点与 `state["messages"]` 存在一个设计约束：

```
state["messages"] = [Human("Q1"), AI("A1"), Human("Q2")]  ← Q2 当前轮
                                   ↓
memory 节点 summarize → 若误删 Q2 →
                                   ↓
chat_history 失去当前轮，state["question"]="Q2" 仍在但上下文断裂
```

**契约**：memory 节点必须保留至少最后 1 条 HumanMessage（当前轮次的问题）。

| 策略 | 保留规则 |
|------|---------|
| trim | 保留最后 N 条消息，N ≥ 2（确保 Human+AI 成对） |
| summarize | 保留最后 1 条 HumanMessage 不变，只摘除前面历史 |

此约束需在 Task 2.5 的设计文档中显式记录。

---

## 6. 收益与成本

### 6.1 收益

1. **与 LangGraph 官方模式对齐** — memory 节点直接操作 messages
2. **generate_node 职责内聚** — 输入输出都是 messages，无需关心 context/question 分拆
3. **测试简化** — mock `llm.invoke(msgs)` 比 mock `prompt \| llm` chain 更直接
4. **Task 2.5 实现自然** — 不需要 chat_history 桥接层
5. **RAGChain 与 Workflow 完全解耦** — 零共享导入，各自独立演进

### 6.2 成本

1. **修改范围涉及 8 个文件（3 新增 + 5 修改），~250 行调整**
2. **两套生成路径并行维护** — RAGChain（LCEL）和 Workflow（direct `llm.invoke`）
3. **`src/workflow/prompts.py` 新建** — 模板字符串与 `src/generation/prompts.py` 初始相同，后续可能分化

### 6.3 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| RAGChain 路径被误改 | 低 | RAGChain 完全不碰 |
| 消息组装顺序出错 | 中 | 测试验证；`build_generate_messages` 与 `_build_messages` 一致 |
| few-shot 丢失 | 低 | `build_generate_messages` 内部处理 |
| V1/V2 版本选择丢失 | 低 | `build_generate_messages` 接受 `version` 参数 |
| format_docs 与 prompt 引用指令不同步 | 低 | format_docs 格式由单元测试固化契约 |
| generation→workflow 回归影响 | 低 | 完全零耦合，generation 修改不影响 workflow |

---

## 7. 与 Task 2.5 的衔接

### 7.1 执行顺序依赖

```
Task 2.4b（基底修正） → Task 2.5（记忆管理）
```

Task 2.5 依赖 Task 2.4b 的修正结果：
- `build_generate_messages` 必须在 `src/workflow/prompts.py` 中可用
- `format_docs` 在 `src/utils/format.py` 中的位置必须稳定
- `create_workflow_nodes` 新签名（不含 prompt）必须确认

### 7.2 修正后的 Task 2.5 数据流

```text
memory 节点（新增）：
  state["messages"] → trim / summarize → RemoveMessage + 摘要 → 写回
  约束：保留至少最后 1 条 HumanMessage（当前轮次）

generate 节点（修正后）：
  state["messages"]（memory 已处理）+ state["documents"] + state["question"]
    → build_generate_messages(context, question, chat_history)
    → llm.invoke(messages)

图拓扑变更： retrieve → [memory] → generate
```

### 7.3 路径对比

| 维度 | 修复基底 + memory | 保留基底 + memory + chat_history |
|------|------------------|--------------------------------|
| 改动范围 | 8 个文件 ~250 行（3 新增 + 5 修改） | 3 个文件 ~50 行 |
| 与官方模式对齐 | 完全对齐 | 不对齐 |
| 记忆管理层数 | 1 层（messages 直接输入） | 2 层（chat_history 桥接） |
| 架构耦合度 | 零耦合（workflow ↔ generation 无共享导入） | 耦合（workflow 依赖 generation） |
| 测试改动 | 大 | 小 |
| 风险等级 | 中 | 低 |

---

## 8. 决策建议

如果 **Task 2.2-2.4 的 Workflow 代码已稳定且通过测试（当前为是）**，且**预期 Phase 3-5 中 Workflow 路径仍会继续演进（是）**，则建议修正基底。偏差暴露在早期（Phase 2 的 Task 2.5），修正成本最低；越往后累积的代码越多，修正成本越高。
