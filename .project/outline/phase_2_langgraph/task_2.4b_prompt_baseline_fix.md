## Task 2.4b Workflow Prompt 基底修正（重构前置）

### 任务目标
消除 Workflow 路径中 generate_node 对 LCEL chain 的依赖，改为通过纯函数构建消息列表后直接调用 `llm.invoke(messages)`，与 LangGraph 官方模式对齐。同时将 `format_docs` 从 `rag_chain.py` 搬迁到 `prompts.py`，消除 RAGChain 路径与 Workflow 路径之间除 prompts.py 外的最后一个耦合点。

**设计约束**（此 Task 产出的决策与 Task 2.5 共同生效）：
- 第 0 层（用户画像）：学习生产级增量重构与 LangGraph 官方模式对齐
- 第 1 层（质量准则 1/3/9）：模块分离避免职责混杂，依赖倒置避免硬编码，可测试性支持 mock llm.invoke
- 第 2 层（Task 指令）：原有 LCEL prompt + context/question 变量 → 改为 messages 直接输入
- 第 3 层（前瞻性边界）：不做多余抽象，仅去掉 LCEL 中间层，不做 memory 节点（留给 Task 2.5）

### 涉及文件

**新增文件：**
- `src/workflow/prompts.py`（NEW）— workflow 自有 prompt 模板 + `build_generate_messages()` + `FEW_SHOT_EXAMPLES`
- `src/utils/format.py`（NEW）— `format_docs()` 从 `rag_chain.py` 搬迁至此
- `src/utils/citation.py`（NEW）— `CitationExtractor` + `CitationExtractionError` + 所有数据结构从 generation 搬迁至此

**修改文件（workflow 路径）：**
- `src/workflow/nodes.py` — 移除 `prompt` 参数、LCEL chain，改为调 `build_generate_messages()` + direct `llm.invoke`；导入改为从 `src.workflow.prompts` + `src.utils.*`
- `src/workflow/builder.py` — 不再获取 prompt 传入 nodes，无 generation 导入

**修改文件（generation 路径，向后兼容）：**
- `src/generation/rag_chain.py` — `format_docs` 定义移除，改为从 `src.utils.format` 导入并 re-export
- `src/generation/citation_chain.py` — 改为从 `src.utils.citation` 导入并 re-export
- `src/generation/exceptions.py` — `CitationExtractionError` 改为从 `src.utils.citation` 导入并 re-export

**测试文件：**
- `tests/test_workflow_nodes.py`（适配签名变化 + mock 方式变化）
- `tests/test_workflow_builder.py`（适配 builder 变化）
- `tests/test_prompts.py`（新增 format_docs 测试）

### 面试级知识点
- **LCEL chain 的本质**：`|` 操作符将 `ChatPromptTemplate | BaseChatModel` 组合为 `Runnable`，其 `invoke` 接收 dict 返回 AIMessage。去掉后直接 `llm.invoke(messages)` 更底层、更灵活。
- **纯函数 vs LCEL chain**：`build_generate_messages` 是纯函数（无副作用），`prompt | llm` 是 Runnable 组合。纯函数更易测试、更透明。
- **中立共享层**：两路径共享的纯函数（如 `format_docs`、`CitationExtractor`）从任一消费者的宿主文件搬迁到 `src/utils/`。这是模块解耦的信号——当两个消费者属于不同架构路径时，共享代码放在中立位置，避免一方的修改影响另一方。
- **`with_retry` 的透明性**：`with_retry(lambda msgs: llm.invoke(msgs))` 展示 retry 包装与参数类型无关——只要是 callable 即可。

### 生产级注意事项
- **`build_generate_messages` 与 `_build_messages` 的一致性**：两者必须使用同一套 `PROMPT_REGISTRY`，避免 RAGChain 路径和 Workflow 路径产生不同的 LLM 输入。
- **`format_docs` 搬迁后的兼容性**：`rag_chain.py` 从 `src.utils.format` 导入 `format_docs` 而非在本文件定义。外部导入 `from src.generation.rag_chain import format_docs` 继续生效（rag_chain.py 通过导入将 format_docs 保留在模块命名空间中）。同理 `CitationExtractor` 通过 `citation_chain.py` re-export，`CitationExtractionError` 通过 `exceptions.py` re-export。
- **`rag_chain.py` 的 `format_docs` 引用清理**：检查所有 import `format_docs` 的地方，`src.workflow.*` 改为从 `src.utils.format` 导入，`src.generation.*` 继续通过 `rag_chain.py` 导入。
- **`build_generate_messages` 的 keyword-only 参数**：使用 `*` 分隔符强制关键字传参，避免 positional 混淆。

### 验收标准
- `src/workflow/prompts.py` 新建，包含：prompt 模板字符串、`FEW_SHOT_EXAMPLES`、`build_generate_messages()`。
  `build_generate_messages(context, question, chat_history, *, version, include_few_shot)` 返回 `list[BaseMessage]`，消息顺序为：System → [Few-shot] → chat_history → Human。
- `src/utils/format.py` 新建，包含 `format_docs()`（从 `rag_chain.py` 搬迁）。
- `src/utils/citation.py` 新建，包含 `CitationExtractor` + `CitationExtractionError` + 所有数据结构（从 generation 搬迁）。
- `create_workflow_nodes` 签名不再含有 `prompt` 参数。
- generate_node 内部使用 `build_generate_messages` 构建消息列表后调用 `llm.invoke(messages)`，不走 `prompt | llm` 链。
- workflow 路径**完全不导入** `src.generation.*`（所有依赖通过 `src.workflow.prompts` + `src.utils.*` 满足）。
- builder.py 不再调用 `get_prompt` 和传入 prompt 到 `create_workflow_nodes`。
- RAGChain 路径（`app.py` / `create_rag_chain`）完全不受影响。
  - `from src.generation.rag_chain import format_docs` 继续生效
  - `from src.generation.citation_chain import CitationExtractor` 继续生效
  - `from src.generation.exceptions import CitationExtractionError` 继续生效
- 所有已有测试通过（`test_workflow_nodes.py`、`test_workflow_builder.py`、`test_prompts.py` 等）。
