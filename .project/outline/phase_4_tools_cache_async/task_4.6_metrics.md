## Task 4.6 综合性能调优与监控埋点

### 任务目标
为系统添加全面的性能监控埋点,识别瓶颈环节,并基于监控数据进行针对性调优,确保 Phase 5 服务化前系统已具备生产级可观测性。

### 涉及文件
- `src/utils/metrics.py`(性能指标收集)
- `src/utils/logger.py`(结构化日志增强)
- `src/core/callbacks.py`(LangChain 回调钩子)

### 面试级知识点
- **RAG 系统的关键性能指标(KPI)**:① 端到端延迟(P50/P95/P99);② 首 Token 延迟(TTFT);③ Token 生成速度(tokens/s);④ 检索延迟;⑤ LLM API 调用延迟;⑥ 缓存命中率;⑦ 错误率。
- **LangChain Callbacks 的作用**:通过继承 `BaseCallbackHandler`,可以在 LLM 调用开始/结束、检索开始/结束等生命周期节点插入自定义逻辑(如计时、日志、指标上报)。
- **分布式追踪的必要性**:当系统拆分为多个微服务时,单个请求可能跨越检索服务、LLM 网关、缓存服务。使用 OpenTelemetry 或 LangSmith 实现全链路追踪,是生产级系统的标配。
- **性能瓶颈的常见位置**:① 向量检索(磁盘 IO、embedding 计算);② Reranker(CPU/GPU 推理);③ LLM 生成(网络延迟、Token 生成速度);④ 网络搜索(外部 API 延迟)。

### 生产级注意事项
- **使用** `time.perf_counter` **进行高精度计时**:在节点函数内部记录关键步骤耗时,并通过 `structlog` 输出为结构化字段(如 `{"retrieval_duration_ms": 152.3}`)。
- **LangChain Callback 集成**:创建 `PerformanceCallbackHandler`,在 `on_llm_start`、`on_llm_end` 中记录 Token 消耗和耗时。将 callback 传入 `graph.ainvoke(config={"callbacks": [perf_callback]})`。
- **指标聚合与导出**:开发环境将指标打印到日志;生产环境通过 `statsd` 或 Prometheus 格式暴露 `/metrics` 端点(Phase 5 实现)。
- **慢查询分析**:设置阈值(如检索 > 500ms,LLM 调用 > 5s),日志中标记 `"slow_query": true`,便于事后分析。
- **基于监控数据的调优决策**:例如,若发现检索延迟占比超过 50%,可考虑:① 减少 `top_k`;② 切换更快的 Embedding 模型;③ 使用 GPU 加速 Embedding 计算。

### 验收标准
- 每次问答请求的日志中必须包含以下字段:`total_duration_ms`、`retrieval_duration_ms`、`llm_duration_ms`、`llm_token_usage`、`cache_hit`。
- 实现 `PerformanceCallbackHandler` 并集成到图运行流程中。
- 编写 `src/evaluation/perf_report.py` 脚本,解析日志文件,生成性能报告(含各环节耗时分布直方图、P95 延迟)。
- 对典型问题(如"What is LangChain?")进行 50 次调用,P95 端到端延迟 < 5 秒(含 LLM 生成时间)。
- 识别并优化至少一个性能瓶颈(如将 Chroma 的 `similarity_search` 结果缓存,或调整 `top_k` 参数),并在报告中记录优化前后对比。
