# 项目上下文索引（AI 专用）

> ⚠️ 定位文件/类/函数/配置时，先查本文件再操作，禁止盲目搜索（见 CLAUDE.md「定位优先规则」）
> 用途：AI 会话启动时一次性读取，提供精准定位信息，避免探索式搜索
> 更新时机：Task 状态变更 / 模块结构变化 / 新增公共导出

---

## ⚙️ 自动维护规则

> **本文件由 AI 在 Task 执行完成时一次性自动更新，无需人工提醒：**
> **更新原则**：增量修改，不重写全文。只有变更的部分才需更新。

---

## 📍 当前 Task

- **Task 1.9 状态** → ✅ 完成（Prompt 接口修复与代码质量改善）
- **Phase 1 Task 1.0~1.8 已完成**，Task 1.10~1.11 待执行
- **Phase 2 待开始**

---

## 📦 核心模块定位表

> 一行定位：模块 → 文件 → 主类/函数 → 职责

| 模块 | 文件 | 主类 / 函数 | 职责 |
|------|------|------------|------|
| 配置管理 | `src/core/config.py` | `deepseek_llm` `qwen_llm` `ollama_embeddings` | LLM/Embedding 实例化（环境变量驱动）⚠️ Task 1.10 将重构为 Settings + 工厂模式 |
| 异常体系 | `src/core/exceptions.py` | `RAGSystemError` `RetryableError` `NonRetryableError` | 分层异常基类 |
| 数据采集 | `src/ingestion/crawler.py` | `crawl_and_save()` | HTML→Markdown 爬取 |
| 文档加载 | `src/ingestion/loader.py` | `load_directory()` `load_markdown_with_frontmatter()` `load_metadata_index()` `enrich_docs_with_index()` | 多源文档加载 + 元数据整合 |
| 文档切分 | `src/ingestion/splitter.py` | `SmartDocumentSplitter` | 标题感知分块 + metadata 传播 |
| 向量入库 | `src/ingestion/vectorstore.py` | `ingest_to_chroma()` | Chroma 向量库写入 |
| 入库流水线 | `src/ingestion/load_data.py` | `run_pipeline()` | 端到端入库编排 |
| 基础检索 | `src/retriever/base_retriever.py` | `VectorRetriever` `create_vector_retriever()` `get_vectorstore()` | 向量检索封装（单例 + 日志 + 异常转换） |
| Prompt 工程 | `src/generation/prompts.py` | `PromptVersion` `get_prompt()` `PROMPT_REGISTRY` | 模板版本管理（V1/V2）+ few-shot + 对话历史占位符 |
| RAG 链 | `src/generation/rag_chain.py` | `RAGChain` `RAGResponse` `format_docs()` | 问答链组装 + 流式输出 |
| 引用提取 | `src/generation/citation_chain.py` | `CitationExtractor` `Citation` `ValidatedCitation` | 引用标记提取 + URL 验证 |
| 生成异常 | `src/generation/exceptions.py` | `GenerationError` `CitationExtractionError` `EmptyRetrievalError` `LLMCallError` | 生成模块异常体系 |
| 检索评估 | `src/evaluation/retrieval_eval.py` | `RetrievalEvaluator` `ExactSourceMatcher` `SourceMatcher` `run_baseline_eval()` | HitRate/MRR/NDCG 评估 |
| 评估指标 | `src/evaluation/metrics.py` | `hit_rate_at_k()` `mrr_at_k()` `ndcg_at_k()` | 底层指标计算 |
| 评估数据集 | `src/evaluation/dataset.py` | `EvalSample` `load_eval_dataset()` | QA pairs 加载 + 结构化日志 |
| 结构化日志 | `src/utils/logger.py` | `setup_logging()` `bind_request_id()` `unbind_request_id()` | structlog 配置 + 请求 ID 绑定 |
| 重试机制 | `src/utils/retry.py` | `create_llm_retry_decorator()` `with_retry()` | tenacity 重试 + 指数退避 |
| CLI 入口 | `src/app.py` | `main()` `cli_loop()` `ChatSession` | REPL 交互 + RAGChain 调用 |
| 启动脚本 | `src/run.py` | `main()` | 标准入口守卫（`python src/run.py`） |

### 关键配置变量（`src/core/config.py`）

| 变量 | 环境变量 | 用途 |
|------|---------|------|
| `DEEPSEEK_API_KEY` | `DEEPSEEK_API_KEY` | DeepSeek LLM API Key |
| `DEEPSEEK_BASE_URL` | `DEEPSEEK_BASE_URL` | DeepSeek API Base URL |
| `QWEN_API_KEY` | `QWEN_API_KEY` | Qwen LLM API Key |
| `QWEN_BASE_URL` | `QWEN_BASE_URL` | Qwen API Base URL |
| `TAVILY_API_KEY` | `TAVILY_API_KEY` | Tavily 搜索 API Key（Phase 4） |

> ⚠️ Task 1.10 完成后，配置变量将迁移到 `src/core/settings.py` 的 `Settings` 类

---

## 🔗 路径速查

### Phase 目录映射（不可推导，必须查表）

| Phase | outline 目录 | tasks 目录 |
|-------|-------------|-----------|
| 1 | `phase_1_reliable_base` | `phase_1` |
| 2 | `phase_2_langgraph` | `phase_2` |
| 3 | `phase_3_retrieval_enhance` | `phase_3` |
| 4 | `phase_4_tools_cache_async` | `phase_4` |
| 5 | `phase_5_serve` | `phase_5` |

### 文档路径构造规则

将上表目录名代入 `DIR` 占位符：

| 类型 | 路径模式 |
|------|---------|
| Phase 总目标 | `.project_outline/DIR/phase_X_goal.md` |
| Task 需求 | `.project_outline/DIR/task_X.X_*.md` |
| 架构设计 | `.project_tasks/DIR/task_X.X_design.md` |
| 技术文档 | `docs/task_X.X/*.md` |

### 关键数据文件

| 文件 | 路径 |
|------|------|
| QA 评估对 | `data/eval/qa_pairs.json` |
| 基线检索报告 | `data/eval/baseline_retrieval_report.md` |
| 规范模板 | `project_info/task_doc_design_spec.md` / `project_info/tech_doc_design_spec.md` / `project_info/task_execution_spec.md` |

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
