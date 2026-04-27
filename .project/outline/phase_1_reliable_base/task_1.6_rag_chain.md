## Task 1.6 基础 RAG Chain（LCEL 实现）

### 任务目标
使用 LangChain Expression Language (LCEL) 构建端到端 RAG 链，集成检索器和 LLM。

### 涉及文件
- `src/generation/rag_chain.py`
- `src/generation/citation_chain.py`

### 面试级知识点
- **LCEL 的 Runnable 协议**：`RunnablePassthrough`、`RunnableLambda`、`RunnableParallel` 如何组合。
- **上下文格式化**：`format_docs` 函数如何将检索到的文档拼接为单个字符串。
- **结构化输出 vs 自由文本**：`with_structured_output` 的使用场景与限制（需模型支持 Function Calling）。

### 生产级注意事项
- **流式输出支持**：Chain 必须返回 `AsyncIterator` 或支持 `.stream()` 方法，为后续 FastAPI 做准备。
- **错误处理**：在 Chain 中捕获 `OpenAIError` 或 `HTTPError`，包装为自定义异常后向上抛出。
- **Fallback 策略**：检索返回空文档时，Chain 应直接返回预设回复，而非调用 LLM。
- **引用生成的可选实现**：如果 LLM 不支持结构化输出，则采用"文本解析"后备方案（正则提取引用标记）。

### 验收标准
- 运行 `python src/app.py` 进入 CLI，输入 Task 1.2 中的一个问题，获得中文回答和来源引用。
- 回答中至少包含 2 条引用，且引用 URL 真实存在于向量库的 metadata 中。
- 重复相同问题，两次回答的引用应基本一致（验证非随机性）。
