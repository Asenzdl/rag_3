### Task 2.6 文档评估与自适应路由

### 任务目标
增加文档评估节点，判断检索结果的相关性；不相关时触发查询重写或网络搜索（为 Phase 4 工具调用预留接口）。

### 涉及文件
- `src/workflow/nodes.py`（新增 `grade_documents` 节点）
- `src/workflow/edges.py`（新增评估分支）

### 设计指导
- 官方文档：langgraph mcp（Agentic RAG 的 `grade_documents` 模式、条件边路由）
- context 7：CLI 工具
- AI 自身的判断

### 验收约束（设计）
- [ ] `grade_documents` 节点对每轮检索结果输出相关性评分（binary: 相关/不相关），评分模型通过 `with_structured_output` + Pydantic `BaseModel` 实现
- [ ] 全部不相关时，经条件边路由至 `rewrite_question`，改写后重新检索 + 重新评分
- [ ] 查询重写存在硬性次数上限（默认 1 次），超过后走降级路径到 generate
- [ ] 部分相关时，不相关块排除、相关块保留送入 generate
- [ ] 降级路径为 Phase 4 工具调用预留条件边分支名（当前只声明不实现）
- [ ] `grade_documents` 和 `rewrite_question` 为纯函数，不依赖 graph 运行时状态

### 面试知识点
- **检索后评估**：RAG 假设"检索到的就是相关的"在实践中频繁失效，评估节点是第一道防线
- **结构化输出**：`with_structured_output` + Pydantic 让 LLM 评分输出类型安全、可编程
- **条件边路由**：`add_conditional_edges(source_node, routing_fn, mapping)` 实现分支逻辑
- **查询重写**：LLM 改写问题为更利于检索的形式，核心约束是"最小修改原则"
- **有状态循环终止**：rewrite → retrieve → grade 循环必须有计数终结或条件终结
