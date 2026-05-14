# Task 2.6 文档评估与自适应路由

## 任务目标
增加文档评估节点，判断检索结果的相关性；不相关时触发查询重写或网络搜索（为 Phase 4 工具调用预留接口）。

## 涉及文件
- `src/workflow/nodes.py`（新增 `grade_documents`、`rewrite_question` 节点）
- `src/workflow/edges.py`（新增评估条件边与路由逻辑）

## 设计指导
- 官方文档：langgraph mcp（Agentic RAG 的 `grade_documents` 模式、条件边路由等等）
- context 7：CLI 工具
- AI 自身的判断

## 面试知识点
- **检索后评估**：RAG 假设“检索到的就是相关的”在实践中频繁失效，评估节点是第一道防线
- **结构化输出**：`with_structured_output` + Pydantic 让 LLM 评分输出类型安全、可编程
- **条件边路由**：`add_conditional_edges(source_node, routing_fn, mapping)` 实现分支逻辑
- **查询重写**：LLM 改写问题为更利于检索的形式，核心约束是“最小修改原则”
- **有状态循环终止**：rewrite → retrieve → grade 循环必须有计数终结或条件终结
- **ReAct 模式映射**：文档评估节点对应 ReAct 的“观察（Observation）”阶段，查询重写 / 工具调用对应“行动（Action）”，检索→评估→改写形成完整的推理‑行动‑观察循环

## 生产注意事项与优化
- **性能开销**：逐条评分意味着 LLM 调用次数 = 检索块数（非 1 次），延迟和 token 成本随块数线性增长。`(query_hash, doc_ids)` 缓存可大幅减少重复评估，建议实现带 TTL 的内存缓存。
- **循环控制**：默认 1 次重写已覆盖多数意图模糊场景，复杂应用可配置为 2 次；务必在状态中持久化 `rewrite_count` 避免并发或重试导致的计数异常。
- **二元判断 Prompt**：推荐模板为“给定用户问题和检索到的文档片段，判断文档是否包含回答问题所需的信息。仅回答 YES 或 NO。”配合结构化输出提取布尔值，稳定可靠。
- **降级体验**：最终仍不相关时直接进入 `generate`，让模型基于少量文档或自身知识生成”无法回答”类话术，比直接跳转静态 `fallback` 更自然、更符合对话预期。
- **缓存**：`(query_hash, doc_ids)` 内存缓存可避免相同查询+文档集重复调用 LLM 评分，建议实现但非必须。
- **分支兜底**：若 Phase 4 工具调用短期内无法落地，`tool_call` 分支可临时路由至 `fallback` 节点返回保底话术，保证服务可用性。

## 验收约束（设计）
- [ ] `grade_documents` 节点对每一条检索结果*独立*输出相关性评分（binary: 相关/不相关），评分模型通过 `with_structured_output` + Pydantic `BaseModel` 实现
- [ ] 全部不相关时，经条件边路由至 `rewrite_question`，改写后重新检索 + 重新评分；**部分相关时，过滤掉不相关文档，仅保留相关文档送入 `generate`**
- [ ] 查询重写存在可配置的硬性上限，通过状态字段 `rewrite_count` 计数，默认上限为 1 次，允许在配置中上调至最高 2 次；超过上限后走降级路径至 `generate`（尝试基于已有文档或自身知识生成诚实回答）
- [ ] 为 Phase 4 工具调用预留条件边分支名（如 `tool_call`），当前不实现
- [ ] `grade_documents` 和 `rewrite_question` 为纯函数，不依赖 graph 运行时状态，`rewrite_count` 通过状态传递和返回
- [ ] 测试场景：故意提出向量库中不存在的问题，系统应进入重写循环，达到上限后降级至 `generate`，输出诚实回应（如”根据已有资料，无法提供可靠答案”）