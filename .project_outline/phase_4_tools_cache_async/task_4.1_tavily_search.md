## Task 4.1 Tavily 网络搜索工具集成

### 任务目标
集成 Tavily Search API 作为外部知识补充工具,当文档评估节点判定本地知识库无法回答时,触发网络搜索并基于搜索结果生成回答。

### 涉及文件
- `src/tools/search_tool.py`
- `src/tools/__init__.py`
- `src/workflow/nodes.py`(新增 `web_search` 节点)
- `src/workflow/edges.py`(新增工具调用分支)

### 面试级知识点
- **RAG 系统的"知识边界"问题**:任何本地知识库都不可能覆盖 100% 的用户问题。生产级 RAG 系统必须定义清晰的知识边界——哪些问题由本地库回答,哪些需要外部搜索,哪些直接拒绝回答。工具调用(Tool Calling)是解决这一问题的标准方案。
- **LangGraph 中的 ToolNode**:LangGraph 预置了 `ToolNode` 类,自动处理工具调用的执行和结果回传。自定义工具只需用 `@tool` 装饰器包装即可被图节点调用。
- **ReAct Agent 的简化实现**:Phase 2 的文档评估节点本质上是一个简化版的 ReAct 循环——评估检索结果(Observe)→ 决策下一步行动(Reason)→ 执行工具调用或生成答案(Act)。Tavily 工具的加入使这一循环更加完整。
- **工具调用的成本控制**:每次工具调用都有经济成本(Tavily API 按请求计费)和延迟成本(网络往返),因此需在路由逻辑中谨慎触发,避免滥用。

### 生产级注意事项
- **Tavily API 的限速与配额管理**:Tavily 免费层每月 1000 次请求。生产环境中需在代码中实现:① 请求计数器(基于 SQLite 或 Redis);② 接近配额时发送警告;③ 配额耗尽后自动降级为"无法回答"。
- **搜索结果的后处理**:Tavily 返回的结果包含 `content`、`url`、`score`。需过滤低分结果(如 `score < 0.5`),并将多个结果的 `content` 拼接为统一的上下文格式,再送入生成节点。
- **与本地检索的融合策略**:当本地检索结果部分相关但不够充分时,是否同时调用网络搜索?建议策略:本地检索 + 文档评估后,若判定"不相关"或"部分相关",则触发网络搜索;搜索结果与本地检索结果合并后送入生成节点,并明确标注来源(本地 vs 网络)。
- **Prompt 中的来源区分**:网络搜索结果的引用格式应与本地文档区分,如 `[Web]` 或 `[网络来源]`,防止用户混淆信息权威性。
- **网络搜索的缓存**:相同问题在短期内(如 1 小时)的搜索结果可缓存,减少 API 调用次数。Phase 4.3/4.4 的缓存模块将覆盖此场景。

### 验收标准
- 在 `src/tools/search_tool.py` 中使用 `@tool` 装饰器定义 `tavily_search` 工具,输入为查询字符串,返回为格式化的搜索结果摘要(含 URL)。
- 在 LangGraph 工作流中增加 `web_search` 节点,当 `grade_documents` 返回 `"not_relevant"` 且 `rewrite_count` 已达上限时,跳转到该节点。
- `web_search` 节点调用 Tavily API,将搜索结果存入 `state["web_results"]`,然后跳转到 `generate` 节点。
- `generate` 节点的 Prompt 需能处理 `web_results` 和本地 `documents` 并存的场景,输出时明确标注来源类型。
- 端到端测试:提出一个 LangChain 文档中不存在的问题(如"2025 年 LangChain 有哪些重大更新?"),系统应触发网络搜索,回答中包含网络来源引用。
- 日志中记录每次 Tavily API 调用的耗时和返回结果数量,用于性能分析。
