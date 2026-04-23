## Task 4.3 LLM 响应缓存(SQLite 精确匹配缓存)

### 任务目标
为 LLM 调用添加本地缓存层,对完全相同的问题(包括上下文)直接返回缓存答案,避免重复调用 LLM,显著降低 API 成本和响应延迟。

### 涉及文件
- `src/cache/llm_cache.py`
- `src/core/config.py`(缓存配置)
- `src/workflow/nodes.py`(在生成节点集成缓存)

### 面试级知识点
- **LLM 缓存的两种粒度**:① 精确缓存(Exact Cache)——问题字符串完全匹配时命中,简单可靠但命中率低;② 语义缓存(Semantic Cache)——问题语义相似即命中,命中率高但实现复杂。Phase 4 先实现精确缓存,4.4 再实现语义缓存。
- **LangChain 的 Cache 接口**:LangChain 提供了 `BaseCache` 抽象类,`SQLiteCache` 是其内置实现。理解其 `lookup()` 和 `update()` 方法的工作流,以及如何通过 `set_llm_cache()` 全局启用。
- **缓存键(Cache Key)的设计**:精确缓存的键是 `(prompt_str, model_name, **kwargs)` 的哈希。在 RAG 场景中,相同的用户问题可能因对话历史不同而产生不同的上下文,因此精确缓存更适合无状态场景。
- **缓存失效策略**:基于时间的 TTL(如 24 小时)是最简单的失效策略。更复杂的是基于文档版本——当知识库更新时,缓存全部失效。

### 生产级注意事项
- **使用 SQLite 而非内存缓存**:SQLite 持久化,进程重启后缓存仍有效,且支持并发读取。生产环境中可将缓存数据库放在 `db/llm_cache.db`。
- **缓存命中率的监控**:在日志中记录每次 LLM 调用的 `cache_hit` 字段(True/False),便于分析缓存效益。可通过 Grafana 等工具绘制命中率趋势图。
- **避免缓存污染**:对于非确定性任务(如创意写作、头脑风暴),缓存应禁用或设置极短 TTL。RAG 问答是相对确定性的任务,适合缓存。
- **缓存与流式输出的兼容性**:LangChain 的缓存机制在流式模式下仍有效——首次调用时流式输出并缓存完整响应,后续命中时直接返回完整响应(非流式)。需在 UI 层处理此差异。
- **结合 Phase 4.4 的语义缓存**:精确缓存是基础,语义缓存是增强。两者可共存:先查语义缓存,未命中再查精确缓存,最后调用 LLM。

### 验收标准
- 在 `config.py` 中配置 `enable_llm_cache=True` 时,使用 `SQLiteCache(database_path="db/llm_cache.db")` 初始化 LangChain 全局缓存。
- 编写测试脚本:连续两次调用相同的 RAG 问题,验证第二次调用时日志显示 `cache_hit=True`,且响应时间 < 50ms。
- 缓存数据库文件 `db/llm_cache.db` 成功生成,可通过 SQLite 客户端查看缓存条目数量。
- 在 CLI 中测试多轮对话:相同问题第二次问时,秒级返回缓存答案(无 LLM 调用延迟)。
- 文档化缓存命中率统计方法:运行 `python src/evaluation/cache_stats.py` 输出缓存统计报告。
