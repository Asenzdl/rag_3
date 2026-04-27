# 项目上下文索引（AI 专用）

> ⚠️ 定位文件/类/函数/配置时，先查本文件再操作，禁止盲目搜索（见 CLAUDE.md「定位优先规则」）
> 用途：AI 会话启动时一次性读取，提供精准定位信息，避免探索式搜索
> 按需加载

---

## 📍 当前 Task

- **Task 1.10 状态** → ✅ 完成（配置管理、工厂模式与检索器协议抽象）
- **Phase 1 Task 1.0~1.10 已完成**，Task 1.11 待执行
- **Phase 2 待开始**

---

## 📦 核心模块定位表

一行定位：文件 → 公共 API：C:类/F:函数 → 职责
模块独立性声明：`src/ingestion`（数据预处理管道） 和 `src/evaluation`（检索评估工具） 是离线工具，通常无需关注，要访问时需发起人工申请，并附带理由

### `src/`

> CLI 应用入口 + 启动脚本

| 文件 | 类型 | 公共 API | 职责概要 |
| :--- | :--- | :--- | :--- |
| `src/app.py` | 应用入口 | — | CLI 交互入口：REPL 问答 + 会话状态管理。 |
| `src/run.py` | 启动脚本 | `F:main` | 程序启动入口。 |

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
| `src/utils/retry.py` | `C:NonRetryableError` `C:RetryableError` `F:create_llm_retry_decorator` `F:with_retry` | LLM 调用重试机制。 |


## 🔗 路径速查

### Phase 目录映射

| Phase | outline 目录 |
|-------|-------------|
| 1 | `phase_1_reliable_base` | 
| 2 | `phase_2_langgraph` | 
| 3 | `phase_3_retrieval_enhance` |
| 4 | `phase_4_tools_cache_async` | 
| 5 | `phase_5_serve` | 

### 文档路径模式

> 将 outline 目录名代入 `DIR`

| 类型 | 路径模式 |
|------|---------|
| Phase 目标 | `.project/outline/DIR/phase_X_goal.md` |
| Task 需求 | `.project/outline/DIR/task_X.X_*.md` |
| 架构设计 | `.project/tasks/phase_X/task_X.X_design.md` |
| 技术文档 | `docs/task_X.X/*.md` |

### 关键文件

| 文件 | 路径 |
|------|------|
| QA 评估对 | `data/eval/qa_pairs.json` |
| 规范模板 | `project_info/{task,tech}_doc_design_spec.md`, `task_execution_spec.md` |

---

## 📋 Task 进度

### Phase 1: 可靠基座 + 评估驱动

| Task | 状态 | 产出 |
|------|------|------|
| 1.0 知识库数据集构建 | ✅ 完成 | crawler.py, 原始 Markdown |
| 1.1 数据管道 | ✅ 完成 | loader.py, splitter.py, vectorstore.py |
| 1.2 评估数据集 | ✅ 完成 | qa_pairs.json, dataset.py |
| 1.3 基础检索器 | ✅ 完成 | base_retriever.py |
| 1.4 检索评估指标 | ✅ 完成 | metrics.py, retrieval_eval.py |
| 1.5 Prompt 模板 | ✅ 完成 | prompts.py（V1/V2） |
| 1.6 基础 RAG Chain | ✅ 完成 | rag_chain.py, citation_chain.py |
| 1.7 重试与日志 | ✅ 完成 | retry.py, logger.py |
| 1.8 CLI 与 E2E | ✅ 完成 | app.py |
| 1.9 Prompt 接口修复与代码质量改善 | ✅ 完成 | prompts.py(修复chat_history位置), citation_chain.py(异常拆分), dataset.py(logger替换) |
| 1.10 配置管理、工厂模式与检索器协议抽象 | ⏳ 待执行 | — |
| 1.11 RAGChain 方法拆分与代码质量改善 | ⏳ 待执行 | — |

### Phase 2: LangGraph 骨架 ⏳

> 未开始。进入时读取对应 `task_X.X_*.md` 获取详细需求。

| Task | Outline 文件 |
|------|-------------|
| 2.1 状态定义 | `task_2.1_state.md` |
| 2.2 核心节点 | `task_2.2_nodes.md` |
| 2.3 条件边与图构建 | `task_2.3_builder.md` |
| 2.4 检查点持久化 | `task_2.4_checkpointer.md` |
| 2.5 对话记忆 | `task_2.5_memory.md` |
| 2.6 文档评估与自适应路由 | `task_2.6_adaptive_route.md` |
| 2.7 CLI 升级 | `task_2.7_cli_upgrade.md` |

### Phase 3~5 ⏳

> 未开始。进入时读取对应 `task_X.X_*.md` 获取详细需求。

| Phase | 主题 | Task 清单 |
|-------|------|----------|
| 3 评估驱动检索增强 | MultiQuery / HyDE / Ensemble / Reranker / RAGAS / A-B对比 / 策略固化 | 3.1~3.7 |
| 4 工具+缓存+异步 | Tavily搜索 / MCP服务 / 精确缓存 / 语义缓存 / 异步 / 监控 / 集成测试 | 4.1~4.7 |
| 5 服务化与容器化 | FastAPI / SSE流式 / Gradio UI / Docker / 配置安全 / 部署文档 / 交付归档 | 5.1~5.7 |

---
