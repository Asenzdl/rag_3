## Task 1.9 Prompt 接口修复与代码质量改善

### 任务目标
修复 Prompt 模板中对话历史占位符的位置错误（真实 bug），修正代码质量问题（异常捕获过宽、日志不统一），确保代码在接口正确性和代码质量上达到生产级标准。

**优先级说明**：本 Task 包含真实 bug 修复（`chat_history` 位置错误），应在后续重构 Task 之前执行，避免 bug 被埋没在重构变更中。

### 涉及文件
- 修改 `src/generation/prompts.py`
- 修改 `src/generation/citation_chain.py`
- 修改 `src/evaluation/dataset.py`

### 面试级知识点
- **对话记忆的 Prompt 注入**：通过 `MessagesPlaceholder("chat_history")` 将历史消息列表动态插入 Prompt，是 LangChain 对话链的标准范式。正确的消息顺序为 System → (可选 Few-shot) → **Chat History** → Human（当前问题）。错误顺序会导致模型上下文混乱，影响回答质量。
- **异常捕获粒度**：`except Exception` 是 Python 中最常见的反模式之一。过宽的异常捕获会吞没未预期的错误（如 `MemoryError`、`SystemExit` 的子类），导致问题难以定位。正确做法是捕获最具体的异常类型，让未预期异常向上传播。

### 生产级注意事项
- **Prompt 修复影响范围可控**：Phase 1 未启用 `include_chat_history`，修复不会影响现有功能。但此接口已作为公开 API 暴露，错误顺序会在 Phase 2 Task 2.5 启用对话记忆时导致模型上下文混乱。
- **输入变量校验**：确保 `include_chat_history=True` 时，`input_variables` 包含 `chat_history`，调用方必须传入该参数（即使为空列表）。
- **与 Phase 2 记忆模块对接**：修复后，Phase 2 的记忆模块可直接将裁剪后的消息列表通过 `chat_history` 变量传入，无需额外适配。
- **异常捕获精确化**：`CitationExtractor` 的 `extract()` 方法中 `except (NotImplementedError, Exception)` 应拆分：`NotImplementedError` 单独捕获并向上抛出让 `extract()` 回退到正则策略，其他异常包装为 `CitationExtractionError`。
- **evaluation 模块日志**：`dataset.py` 中的 `print(f"[WARN]...")` 替换为 `logger.warning()`，`print_dataset_stats()` 中的 print 保留（属于 CLI 输出）。

### Phase 2 复用策略
本 Task 修复的接口在 Phase 2 中的复用关系：
- ✅ **复用**：修复后的 `_build_messages` 函数——Phase 2 Task 2.5 生成节点调用 `get_prompt(include_chat_history=True)` 时消费此接口，将 `state["messages"]` 经裁剪/摘要后作为 `chat_history` 传入。注意：Phase 2 **不复用** Phase 1 的 `ChatSession` 记忆管理机制（由 LangGraph `state.messages` + `thread_id` 取代），仅复用 Prompt 模板的消息组装逻辑。
- ❌ **不复用**：`CitationExtractor` 异常处理细节（Phase 2 引用提取节点直接调用 `CitationExtractor`，异常处理策略不影响节点逻辑）
- ❌ **不复用**：`dataset.py` 日志（评估模块在 Phase 2 无变化）

### 验收标准
- 修改 `_build_messages` 函数，将 `MessagesPlaceholder("chat_history")` 移至 `HumanMessagePromptTemplate` 之前。
- 验证消息列表顺序：`SystemMessagePromptTemplate` → （可选 `HumanMessage`/`AIMessage` 对）→ `MessagesPlaceholder("chat_history")` → `HumanMessagePromptTemplate`。
- 测试：`get_prompt(include_chat_history=True).invoke({"context": "...", "question": "...", "chat_history": []})` 正常工作，不抛出异常。
- 编写单元测试，断言消息列表结构符合预期顺序。
- `CitationExtractor` 的 `extract()` 方法中 `except (NotImplementedError, Exception)` 精确化：`NotImplementedError` 单独捕获并向上抛出，其他异常包装为 `CitationExtractionError`。
- `dataset.py` 中 `print(f"[WARN]...")` 替换为 `logger.warning()`。
- Phase 1 CLI 运行不受影响。
