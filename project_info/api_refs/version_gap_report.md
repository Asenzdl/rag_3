# LangChain / LangGraph 版本落差报告

> 训练数据盲区勘误 — 基于官方 RSS changelog 与本地安装版本对比
> 目标：明确 AI 知识边界，避免编造不存在的 API

---

## 版本落差总览

| 包 | 本地版本 | PyPI 最新 | 差距 |
|----|---------|-----------|------|
| langchain-core | 1.3.2 | 1.3.2 | 0 ✅ |
| langchain | 1.2.17 | 1.2.17 | 0 ✅ |
| langgraph | 1.1.10 | 1.1.10 | 0 ✅ |

---

## langgraph

### v1.0.0（2025-10-20）→ [已知]

| 变更 | 判断 |
|------|------|
| `create_react_agent` 废弃 → `langchain.agents.create_agent` | 已知 |
| `MessageGraph` 废弃 → `StateGraph` + `messages` key | 已知 |
| `AgentState` 等类型移到 `langchain.agents` | 已知 |
| Python 3.9 支持终止，最低 3.10 | 已知 |

### v1.1.0（2026-03-10）→ [盲区]

**核心变更：version="v2" streaming**

- `stream(version="v2")` / `astream()` 返回统一 `StreamPart` dict，含 `type`/`ns`/`data` 键
- StreamPart TypedDicts（从 `langgraph.types` 导入）：`ValuesStreamPart` / `UpdatesStreamPart` / `MessagesStreamPart` / `CustomStreamPart` / `TasksStreamPart` / `DebugStreamPart`
- `invoke(version="v2")` 返回 `GraphOutput` 对象 (`.value` + `.interrupts`)，不是原始 dict
- v2 模式下 invoke() / values-mode stream 自动将输出转成声明的 Pydantic model / dataclass

**其他：**
- Subgraphs time travel 修复
- Pydantic/dataclass coercion

### v1.1.2 → [盲区]

- `context` 参数：为**远程图 API** 新增，并非替代 `config_schema`

### v1.1.3 → [本地旧版本]

- Execution info 运行时暴露更多执行信息

### v1.1.4 → [盲区]

- LangSmith integration metadata

### v1.1.7 → [盲区]

- Graph lifecycle callback handlers（图生命周期回调处理器）

### v1.1.10 → [本地当前版本]

- ToolNode 允许 tools 返回 `list[Command | ToolMessage]`

### v1.2.0 alpha → [盲区，未稳定]

- Node-level error handlers
- Graceful shutdown/drain
- `stream_events(version='v3')`
- DeltaChannel（增量 checkpoint 机制）

---

## langchain

### v1.0.0（2025-10-20）→ [已知]

- 包精简，namespace 收窄
- legacy chains/retrievers/indexing/hub → `langchain-classic`
- `create_agent` 替代 `create_react_agent`

### v1.1.0（2025-11-25）→ [盲区]

| 新功能 | 说明 |
|--------|------|
| Model profiles | `chat_model.profile` 属性暴露模型能力信息 |
| ProviderStrategy | structured output 可从 model profile 自动推断 provider |
| SystemMessage 直接传入 | `create_agent(system_prompt=SystemMessage(...))` |
| Model retry middleware | 自动重试失败模型调用，可配置指数退避 |
| Content moderation middleware | OpenAI 内容审核中间件 |

### v1.2.0（2025-12-15）→ [盲区]

| 新功能 | 说明 |
|--------|------|
| Tools extras | `BaseTool.extras` 支持 provider-specific 参数 |
| Strict schema adherence | `response_format` 支持 `ProviderStrategy` 实现严格 schema 校验 |

### v1.2.14-17 → [盲区，patch]

- CVE 修复、aiohttp 升级
- content-block-centric streaming v2 集成（依赖 langchain-core 1.3.x）
- `respond` decision 加入 HITL middleware

---

## langchain-core

### v1.3.0 → [盲区]

- **Content-block-centric streaming v2** — 流式输出协议重构
- 与 langgraph v1.1 `version="v2"` 配合使用

### v1.2.x → [盲区]

- `ContextOverflowError`：Chat model 超上下文窗口时抛出的异常

---

## 废弃 / 破坏性变更汇总

| 包 | 废弃项 | 替代 | 状态 |
|----|--------|------|------|
| langgraph | `create_react_agent` | `langchain.agents.create_agent` | 已知 |
| langgraph | `MessageGraph` | `StateGraph` + `messages` | 已知 |
| langgraph | `AgentState` | `langchain.agents.AgentState` | 已知 |
| langgraph | `ValidationNode` | create_agent 自动验证 | 可能已知 |
| langchain | legacy chains/retrievers | `langchain-classic` | 已知 |
| langchain | `AgentState` pydantic variant | 统一 `AgentState` | 已知 |
| langgraph | v1 stream() 格式 | v2 可选 | 盲区 |

---

## 已修正的 api_refs 错误

> 以下错误已在 `project_info/api_refs/langgraph_compiled_graph.md` 中修正

| 原文 | 问题 | 修正结果 |
|------|------|---------|
| `context` 参数"替代已废弃的 config_schema" | 未在任何 changelog 中找到 `config_schema` 废弃记录 | 改为"v1.1.2 为远程图 API 新增" |
| `bulk_update_state` 列为 v1.1 新功能 | 未在任何 changelog 中出现此方法 | 改为"[不确定版本]" |
| `Durability` 列为 v1.1 新功能 | "Durable execution" 从 v0 就存在 | 改为"[不确定版本]" |
