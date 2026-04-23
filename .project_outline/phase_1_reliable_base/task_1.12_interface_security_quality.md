## Task 1.12 接口修复、安全加固与代码质量

### 任务目标
修复 Prompt 对话历史接口位置错误，消除安全隐患，修正代码质量问题（异常捕获过宽、docstring 示例误导、日志不统一），确保 Phase 1.5 重构后的代码在接口正确性、安全性和代码质量上均达到生产级标准。

### 涉及文件
- 修改 `src/generation/prompts.py`
- 修改 `src/generation/citation_chain.py`
- 修改 `src/generation/rag_chain.py`
- 修改 `src/evaluation/dataset.py`

### 面试级知识点
- **对话记忆的 Prompt 注入**：通过 `MessagesPlaceholder("chat_history")` 将历史消息列表动态插入 Prompt，是 LangChain 对话链的标准范式。正确的消息顺序为 System → (可选 Few-shot) → **Chat History** → Human（当前问题）。错误顺序会导致模型上下文混乱，影响回答质量。
- **异常捕获粒度**：`except Exception` 是 Python 中最常见的反模式之一。过宽的异常捕获会吞没未预期的错误（如 `MemoryError`、`SystemExit` 的子类），导致问题难以定位。正确做法是捕获最具体的异常类型，让未预期异常向上传播。


### 生产级注意事项
- **Prompt 修复影响范围可控**：Phase 1 未启用 `include_chat_history`，修复不会影响现有功能。但此接口已作为公开 API 暴露，错误顺序会在 Phase 2 Task 2.5 启用对话记忆时导致模型上下文混乱。
- **输入变量校验**：确保 `include_chat_history=True` 时，`input_variables` 包含 `chat_history`，调用方必须传入该参数（即使为空列表）。
- **与 Phase 2 记忆模块对接**：修复后，Phase 2 的记忆模块可直接将裁剪后的消息列表通过 `chat_history` 变量传入，无需额外适配。
- **异常捕获精确化**：`CitationExtractor._extract_structured` 中的 `except (NotImplementedError, Exception)` 应拆分为两个 except 块：`NotImplementedError` 向上抛出让 `extract()` 回退到正则策略，其他异常包装为 `CitationExtractionError`。
- **docstring 示例更新**：`RAGChain` 的模块级 docstring 中的使用示例应更新为使用工厂函数，不再展示直接导入 `deepseek_llm` 的方式，避免误导 AI 和开发者。
- **evaluation 模块日志**：`dataset.py` 中的 `print(f"[WARN]...")` 替换为 `logger.warning()`，`print_dataset_stats()` 中的 print 保留（属于 CLI 输出）。

### 验收标准
- 修改 `_build_messages` 函数，将 `MessagesPlaceholder("chat_history")` 移至 `HumanMessagePromptTemplate` 之前。
- 验证消息列表顺序：`SystemMessagePromptTemplate` → （可选 `HumanMessage`/`AIMessage` 对）→ `MessagesPlaceholder("chat_history")` → `HumanMessagePromptTemplate`。
- 测试：`get_prompt(include_chat_history=True).invoke({"context": "...", "question": "...", "chat_history": []})` 正常工作，不抛出异常。
- 编写单元测试，断言消息列表结构符合预期顺序。
- `CitationExtractor._extract_structured` 中异常捕获精确化：`NotImplementedError` 单独捕获并向上抛出，其他异常包装为 `CitationExtractionError`。
- `rag_chain.py` 模块级 docstring 中的使用示例更新为使用工厂函数（`from src.core.factories import create_rag_chain`），不再展示 `from src.core.config import deepseek_llm`。
- `dataset.py` 中 `print(f"[WARN]...")` 替换为 `logger.warning()`。
- `.env`，列出所有必需和可选环境变量及默认值说明。
- Phase 1 CLI 运行不受影响。
