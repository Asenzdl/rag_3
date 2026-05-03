# 前瞻性设计约束

> 从所有 Task 文档中提取的显式跨阶段约束。
> 每条都是任务文档中明确要求的，不是"可能有用"的推测。
> MUST = 必须在当前 Task 中覆盖，否则后续 Phase 会出问题。

---

## Phase 1 → Phase 2 约束

### 1. RAGChain 流式接口（源：1.6 → 目标：Phase 5）
- Chain 必须暴露 `.stream()` 方法
- 原因：Phase 5 FastAPI 流式响应依赖此接口
- 约束：`.stream()` 必须在 Phase 1 正确实现，不是占位

### 2. `_build_messages` chat_history 修复（源：1.9 → 目标：2.5）
- 即使 Phase 1 未启用 `include_chat_history`，占位符顺序必须正确
- 原因：Phase 2 Task 2.5 对话记忆会传入真实的历史消息列表，错误顺序会导致模型上下文混乱
- 约束：修复后 Phase 2 可直接通过 `chat_history` 变量传入裁剪后的消息列表，无需额外适配

### 3. Checkpoint 配置预留（源：1.10 → 目标：2.4）
- `Settings` 必须包含 `checkpoint_db_path` 字段，默认 `db/checkpoints.db`
- 原因：Phase 2 Task 2.4 构建 SqliteSaver 时需要此配置
- 约束：Phase 1 不使用检查点，但配置字段必须就位

### 4. 工厂/协议通用化（源：1.10 → 目标：2.x）
- `factories.py` 和协议类必须设计为通用依赖组装器，不与 Phase 1 的 RAGChain 编排耦合
- 原因：Phase 2 的 `builder.py` 会直接调用这些工厂构造组件，绕过 RAGChain
- 约束：工厂函数的依赖关系要清晰，不隐含 Phase 1 特有的编排逻辑

### 5. RAGChain 方法拆分（源：1.11 → 目标：2.2）
- 方法拆分必须解耦"编排逻辑"和"执行步骤"
- 原因：Phase 2 节点函数将直接调用底层组件（retriever、LLM、CitationExtractor），不经过 RAGChain 编排
- 私有步骤方法不应被设计为 Phase 2 的公共 API

### 6. `ainvoke()` 占位规则（源：1.11 → 目标：4.5）
- 标记为 `raise NotImplementedError`
- docstring 注明"当前为占位，Task 4.5 应独立评估"
- 禁止假异步实现（如 `async def ainvoke(): return self.invoke()`）

### 7. 可复用工具与编排分离（源：1.11 → 目标：2.x）
- `format_docs()`、`CitationExtractor`、`RAGResponse` 必须与 RAGChain 编排逻辑解耦
- RAGChain 类在 Phase 2 过渡期间保留为兼容入口，Phase 2.7 后废弃

---

## Phase 2 → Phase 4 约束

### 8. 自适应路由预留 tool_call 节点（源：2.6 → 目标：4.1）
- 条件边路由图中必须包含 `tool_call` 节点槽
- 原因：Phase 4 Task 4.1 Tavily 搜索集成需要填充此节点
- 约束：Phase 2 实现中 `tool_call` 可先跳转到 fallback，但节点名称和路由分支必须存在
- 不预留的后果：Phase 4 需要重写图拓扑

### 9. 条件边必须引用 Phase 4 节点名称（源：2.6 → 目标：4.1）
- 当重写次数耗尽或评估仍不相关时，跳转到 `tool_call` 节点
- 原因：与第 8 条配合，确保路由逻辑在 Phase 4 只需替换节点实现，不改路由结构

---

## Phase 3 → Phase 4 约束

### 10. Fallback 链扩展点（源：3.7 → 目标：4.1）
- 策略固化时必须为 Tavily 搜索预留 fallback 扩展点
- 原因：Phase 4 的搜索集成需要作为检索链之外的最后手段注入
- 约束：Fallback 链顺序为 Base → MultiQuery → [Phase 4 Tavily Search]

---

## Phase 4 → Phase 5 约束

### 11. 全异步化先决条件（源：4.5 → 目标：5.1）
- 所有检索器必须实现 `aretrieve` 方法
- 图节点必须支持异步（`async def node(state)`）
- 原因：Phase 5 FastAPI 需要非阻塞端点，同步调用会阻塞事件循环
- 约束：`FastAPI 端点能正确调用 await graph.ainvoke(...)` 是 Phase 5 验收标准

---

## SHOULD / NICE 级别约束

| 源 | 约束 | 级别 | 原因 |
|----|------|------|------|
| 1.10 | `vectorstore_type` 配置字段为后续迁移预留 | NICE | 未来切换到 FAISS/Pinecone 时不需要改 Settings 结构 |
| 4.6 | 指标收集层与 HTTP 导出解耦 | NICE | Phase 5 通过 `/metrics` 端点负责生产级导出，指标层不应硬编码输出方式 |
| 5.1 | API 路由使用 `/api/v1/` 前缀 | NICE | 未来 API 变更可共存于 `/api/v2/` 下 |
