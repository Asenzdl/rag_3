# 项目上下文索引（AI 专用）

> ⚠️ 定位 文件/类/函数/配置时，先查本文件再操作，禁止盲目搜索（见 CLAUDE.md「定位优先规则」）
> 用途：AI 会话启动时一次性读取，提供精准定位信息，避免探索式搜索
> 单会话只会完成一个 Task，且会严格更新此文件，请信任此文件的定位信息
> **按需加载**

---

## 📦 核心模块定位表

一行定位：文件 → 公共 API：C:类/F:函数/R:Re-export → 职责
模块独立性声明：`src/ingestion`（数据预处理管道） 和 `src/evaluation`（检索评估工具） 是离线工具，通常无需关注，要访问时需发起人工申请，并附带理由

### `src/`

> CLI 应用入口 + 启动脚本

| 文件 | 公共 API | 职责概要 |
| :--- |:--- | :--- |
| `src/app.py` | — | CLI 交互入口：应用入口 + REPL 问答 + 会话状态管理。 |
| `src/run.py` | `F:main` | 启动脚本：程序启动入口。 |

### `src/core/`

> core 包 — 核心基础设施：配置管理、工厂函数、异常体系。

| 文件 | 公共 API | 职责概要 |
| :--- | :--- | :--- |
| `src/core/config.py` | `F:settings` | 配置入口门面 — 加载环境变量 + 导出 Settings 单例。 |
| `src/core/exceptions.py` | `C:NonRetryableError` `C:RAGSystemError` `C:RetryableError` | RAG 系统统一异常体系。 |
| `src/core/factories.py` | `F:create_embeddings` `F:create_llm` `F:create_rag_chain` `F:create_retriever` `F:create_vectorstore` | 工厂函数模块 — 配置驱动的对象创建。 |
| `src/core/settings.py` | `C:Settings` | 12-Factor App 配置管理 — Pydantic BaseSettings 实现。 |

### `src/generation/`

> generation 包 — RAG Chain 生成层核心 API。

| 文件 | 公共 API | 职责概要 |
| :--- | :--- | :--- |
| `src/generation/citation_chain.py` | `C:Citation` `C:CitationExtractor` `C:ValidatedCitation` | 引用提取与验证模块。 |
| `src/generation/exceptions.py` | `C:CitationExtractionError` `C:EmptyRetrievalError` `C:GenerationError` `C:LLMCallError` | 生成模块异常定义。 |
| `src/generation/prompts.py` | `C:PromptVersion` `F:get_prompt` | Prompt 模板定义与版本管理模块。 |
| `src/generation/rag_chain.py` | `C:RAGChain` `C:RAGResponse` `F:format_docs` | RAG 问答链模块：LCEL 组合 + 空检索拦截 + 流式支持。 |

### `src/retriever/`

> retriever 包 — 检索层核心 API。

| 文件 | 公共 API | 职责概要 |
| :--- | :--- | :--- |
| `src/retriever/base_retriever.py` | `C:RetrievalError` `C:UnsupportedSearchTypeError` `C:VectorRetriever` | 基础向量检索器：封装 Chroma 向量检索器。 |
| `src/retriever/protocols.py` | `C:RetrieverProtocol` | 检索器协议定义 — 结构子类型（Structural Subtyping）。 |

### `src/utils/`

> utils 包 — 基础设施工具模块。

| 文件 | 公共 API | 职责概要 |
| :--- | :--- | :--- |
| `src/utils/logger.py` | `F:bind_request_id` `F:setup_logging` `F:unbind_request_id` | 结构化日志配置模块。 |
| `src/utils/retry.py` | `R:NonRetryableError` `R:RetryableError` `F:create_llm_retry_decorator` `F:with_retry` | LLM 调用重试机制。 |

### `src/workflow/`

> workflow 包 — LangGraph 工作流定义：状态、节点、图构建、检查点持久化。

| 文件 | 公共 API | 职责概要 |
| :--- |:--- | :--- |
| `src/workflow/state.py` | `C:GraphState` | LangGraph 工作流全局状态定义（TypedDict + Annotated + add_messages reducer）。 |
| `src/workflow/nodes.py` | `F:create_workflow_nodes` | LangGraph 节点工厂：闭包注入依赖，返回 route/retrieve/generate 节点字典。 |
| `src/workflow/routing.py` | `F:classify_intent` `F:create_route_prompt` `V:RETRIEVE/GREETING/FALLBACK` | 路由逻辑：意图分类 Prompt + LLM 分类函数 + 路由标签常量。 |
| `src/workflow/builder.py` | `F:build_graph` `V:GREETING_RESPONSE/FALLBACK_RESPONSE` | 图构建：Settings 驱动组装 StateGraph + 可选 checkpointer + 简单终端节点（greeting/fallback）。 |
| `src/workflow/edges.py` | `F:route_after_classification` | 条件边路由函数：route 节点后，根据 route_decision 决定下一跳。 |
| `src/workflow/checkpointer.py` | `F:create_checkpointer` | 检查点持久化工厂：上下文管理器模式封装 SqliteSaver + setup() + 目录自动创建。 |


## 🔗 路径映射

### Phase 目录映射

| Phase | outline 目录 |
|-------|-------------|
| 1 | `phase_1_reliable_base` | 
| 2 | `phase_2_langgraph` | 
| 3 | `phase_3_retrieval_enhance` |
| 4 | `phase_4_tools_cache_async` | 
| 5 | `phase_5_serve` | 

### 文档路径模式

| 类型 | 路径模式 |
|------|---------|
| Phase 目标 | `.project/outline/phase_X_*/phase_X_goal.md` |
| Task 文档 | `.project/outline/phase_X_*/task_X.X_*.md` |
| 架构设计 | `.project/tasks/phase_X/task_X.X_design.md` |
| 技术文档 | `.project/docs/task_X.X/*.md` |

### 数据文件

| 文件 | 路径 |
|------|------|
| QA 评估对 | `data/eval/qa_pairs.json` |

---

### 第三方库 API 参考缓存

> AI 训练数据盲区勘误 — 仅记录 AI 训练数据中不存在或错误的关键 API 差异
> 已有的直接信任，禁止重复查 context7/源码验证

| 文件 | 内容 |
|------|------|
| `project_info/api_refs/langgraph_compiled_graph.md` | CompiledStateGraph 所有 public 方法签名 |
| `project_info/api_refs/langgraph_v2_streaming.md` | LangGraph v2 streaming API 参考 

---

## 📋 Task 目标索引

> 根据目标去判断某个 Task 是否与当前 Task 可能产生前瞻性设计，再具体去阅读其 Task 文档
> 按需阅读Task文档，`.project/outline/phase_X_*/task_X.X_*.md`

### Phase 1: 可靠基座 + 评估驱动

| Task | 目标 |
|------|------|
| 1.0 | LangChain 知识库构建（爬虫 + 文档分离） |
| 1.1 | 数据管道：加载 → 分块 → 向量化 |
| 1.2 | 评估数据集构建（QA 问答对） |
| 1.3 | 基础向量检索器封装（Chroma + MMR） |
| 1.4 | 检索评估指标体系（Hit Rate, MRR） |
| 1.5 | Prompt 模板版本管理（V1/V2） |
| 1.6 | 基础 RAG Chain（LCEL + 空检索拦截 + 引用生成） |
| 1.7 | LLM 重试机制 + 结构化日志 |
| 1.8 | CLI 交互 + E2E 测试 |
| 1.9 | Prompt 接口修复 + 代码质量 |
| 1.10 | 12-Factor 配置 + 工厂模式 + 协议抽象 |
| 1.11 | RAGChain 重构 + 代码质量 |

### Phase 2: LangGraph 骨架

phase 2 大纲汇总：`.project\outline\phase_2_langgraph\phase 2_total_tasks.md`

| Task | 目标 |
|------|------|
| 2.1 | LangGraph 状态定义（StateGraph + TypedDict） |
| 2.2 | 核心节点实现（检索 → 生成 → 引用验证） |
| 2.3 | 条件边与图构建（Conditional Edge） |
| 2.4 | 检查点持久化（SQLite Checkpointer） |
| 2.5 | 对话记忆（短期记忆 + 摘要记忆） |
| 2.6 | 文档评估与自适应路由（自信度路由） |
| 2.7 | CLI 升级（流式输出 + 会话管理） |

### Phase 3: 评估驱动检索增强

| Task | 目标 |
|------|------|
| 3.1 | 多查询检索器（MultiQuery，提升模糊问题召回率） |
| 3.2 | HyDE 假设文档嵌入 |
| 3.3 | 集成检索（Ensemble：多检索器合并） |
| 3.4 | 重排序器（Reranker：Cross-Encoder 精排） |
| 3.5 | RAGAS 评估框架集成 |
| 3.6 | A/B 对比实验（基线 vs 增强策略） |
| 3.7 | 检索策略固化（选择最优方案） |

### Phase 4: 工具 + 缓存 + 异步

| Task | 目标 |
|------|------|
| 4.1 | Tavily 搜索工具集成 |
| 4.2 | MCP 服务集成（Model Context Protocol） |
| 4.3 | LLM 精确缓存（结果级缓存） |
| 4.4 | 语义缓存（Embedding 相似度缓存） |
| 4.5 | 异步支持（Async RAG Chain） |
| 4.6 | 监控与指标（Prometheus + Grafana） |
| 4.7 | 集成测试（端到端验证） |

### Phase 5: 服务化与容器化

| Task | 目标 |
|------|------|
| 5.1 | FastAPI 服务封装 |
| 5.2 | SSE 流式输出 |
| 5.3 | Gradio UI 交互界面 |
| 5.4 | Docker 容器化部署 |
| 5.5 | 配置安全（环境变量 + 密钥管理） |
| 5.6 | 部署文档编写 |
| 5.7 | 交付归档 |

---
