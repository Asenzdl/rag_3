## Task 2.4b Workflow Prompt 基底修正

### 任务目标
消除 Workflow 路径中 generate_node 对 LCEL chain 的依赖，改为通过纯函数构建消息列表后直接调用 `llm.invoke(messages)`，与 LangGraph 官方模式对齐。

**设计约束**（此 Task 产出的决策与 Task 2.5 共同生效）：
- 第 0 层（用户画像）：学习生产级增量重构与 LangGraph 官方模式对齐
- 第 1 层（质量准则 1/3/9）：模块分离避免职责混杂，依赖倒置避免硬编码，可测试性支持 mock llm.invoke
- 第 2 层（Task 指令）：原有 LCEL prompt + context/question 变量 → 改为 messages 直接输入
- 第 3 层（前瞻性边界）：不做多余抽象，仅去掉 LCEL 中间层，不做 memory 节点（留给 Task 2.5）

### 实施方案

Workflow 路径持有自己的 prompt 模板和工具函数副本，与 RAGChain 路径完全解耦、各自独立演进。

1. `src/workflow/prompts.py`（新增）— workflow 自有模板 + `build_generate_messages()` + `format_docs()`。
   模板初始值与 `src/generation/prompts.py` 相同，后续可独立修改。`format_docs` 在此处定义而非 utils，因为其输出格式与 prompt 模板的引用格式指令锁步变化，放在同一模块避免断裂。
2. `src/workflow/citation.py`（新增）— workflow 自有引用提取模块副本，包含 `CitationExtractor`、`CitationExtractionError`（继承 `NonRetryableError`）等。与 generation 版本的 `CitationExtractionError(GenerationError, NonRetryableError)` 是不同类，互不影响。
3. `src/generation/` 完全不动 — 无 re-export、无 import 变更、无文件修改。

### 涉及文件

**新增文件：**
- `src/workflow/prompts.py`（NEW）— workflow 自有模板 + `build_generate_messages()` + `format_docs()` + `FEW_SHOT_EXAMPLES`
- `src/workflow/citation.py`（NEW）— workflow 自有引用提取模块（从 generation 副本迁移）

**修改文件（workflow 路径）：**
- `src/workflow/nodes.py` — 移除 `prompt` 参数、LCEL chain，改为调 `build_generate_messages()` + direct `llm.invoke`；导入改为从 `src.workflow.prompts` + `src.workflow.citation`
- `src/workflow/builder.py` — 不再获取 prompt 传入 nodes，无 generation 导入

**未修改文件：**
- `src/generation/` 全部 — 完全恢复为重构前状态，无任何改动
- `src/utils/` — 未使用。`src/utils/format.py` 曾短暂存在后被删除（无消费者），`src/utils/citation.py` 删除（决策见下）

**测试文件：**
- `tests/test_workflow_nodes.py`（适配签名变化 + mock 方式变化）
- `tests/test_workflow_builder.py`（适配 builder 变化）

### 架构决策记录

#### 决策 1：workflow 持有自有副本而非共享 utils

**问题**：`format_docs` 和 `CitationExtractor` 被 RAGChain 和 Workflow 两路径同时使用，应放在何处？

**候选方案**：
- A（共享 utils）：放入 `src/utils/format.py` + `src/utils/citation.py`，两路径统一导入
- B（workflow 自有副本）：`format_docs` 放 `src/workflow/prompts.py`，`CitationExtractor` 放 `src/workflow/citation.py`
- C（交叉依赖）：workflow 从 `src/generation/` 直接导入

**选择 B**，理由：
- `format_docs` 与 prompt 模板引用指令锁步变化，放在同文件（prompts.py）比放 utils 更保一致
- `CitationExtractor` 在 workflow 中仅用正则策略（`use_structured_output=False`），与 RAGChain 的完整版本业务语义不同。副本模式防止一方的变更影响另一方
- 此决断在架构拉扯止损器中的记录：方案 A 依赖"共享代码不会分化"的前提——该前提在当前项目中不成立，因为两路径的技术栈差异会导致独立演进

#### 决策 2：generation 完全不动，无反重构

**问题**：重构是否需要在 `src/generation/` 中引入 re-export 以保证向后兼容？

**选择不修改**。因为：
- 重构只影响 workflow 路径的内部结构，generation 路径的消费方（`app.py`、`create_rag_chain`）不受影响
- 无任何外部代码依赖 workflow 的模块，无需兼容层
- `CitationExtractionError` 在 generation 中继承 `GenerationError`，在 workflow 中继承 `NonRetryableError`——两者是不同类，互不干扰

### 面试级知识点
- **LCEL chain 的本质**：`|` 操作符将 `ChatPromptTemplate | BaseChatModel` 组合为 `Runnable`，其 `invoke` 接收 dict 返回 AIMessage。去掉后直接 `llm.invoke(messages)` 更底层、更灵活。
- **纯函数 vs LCEL chain**：`build_generate_messages` 是纯函数（无副作用），`prompt | llm` 是 Runnable 组合。纯函数更易测试、更透明。
- **副本模式 vs 共享模式**：当两个消费者属于不同架构栈（LCEL vs LangGraph）时，共享模块的稳定假设不成立。副本模式虽然破坏 DRY，但避免了耦合和分化时的协调成本。
- **`with_retry` 的透明性**：`with_retry(lambda msgs: llm.invoke(msgs))` 展示 retry 包装与参数类型无关——只要是 callable 即可。

### 生产级注意事项
- **`build_generate_messages` 与 `_build_messages` 的一致性**：两者初始模板字符串相同，但后续独立演进。修改 prompt 模板时需确认是否需要同步修改另一条路径。
- **`CitationExtractionError` 的双份定义**：generation 版本继承 `GenerationError`，workflow 版本继承 `NonRetryableError`。`except GenerationError` 不能捕获 workflow 版本——这是设计意图，因为 workflow 的异常不需要被 generation 的异常处理器处理。
- **`build_generate_messages` 的 keyword-only 参数**：使用 `*` 分隔符强制关键字传参，避免 positional 混淆。
- **`format_docs` 与 prompt 的锁步关系**：`format_docs` 的输出格式和 prompt 模板的引用格式指令必须匹配。修改一方需同步修改另一方——因在同一文件中（`prompts.py`），容易被注意到。

### 验收标准
- `src/workflow/prompts.py` 新建，包含：prompt 模板字符串、`FEW_SHOT_EXAMPLES`、`format_docs()`、`build_generate_messages()`。
  `build_generate_messages(context, question, chat_history, *, version, include_few_shot)` 返回 `list[BaseMessage]`。
- `src/workflow/citation.py` 新建，包含 workflow 自有版本的 `CitationExtractor`、`CitationExtractionError` 及数据结构。
- `create_workflow_nodes` 签名不再含有 `prompt` 参数。
- generate_node 内部使用 `build_generate_messages` 构建消息列表后调用 `llm.invoke(messages)`，不走 `prompt | llm` 链。
- workflow 路径**完全不导入** `src.generation.*`。
- builder.py 不再调用 `get_prompt` 和传入 prompt 到 `create_workflow_nodes`。
- `src/generation/` 完全不受影响，所有文件无任何变更。
- 所有已有测试通过（`test_workflow_nodes.py`、`test_workflow_builder.py`）。
