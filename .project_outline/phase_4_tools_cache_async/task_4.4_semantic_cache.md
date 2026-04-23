## Task 4.4 语义缓存(Semantic Cache)

### 任务目标
在精确缓存基础上增加语义缓存层,对语义相似(而非完全相同)的用户问题直接返回缓存答案,进一步提升缓存命中率和降低 LLM 成本。

### 涉及文件
- `src/cache/semantic_cache.py`
- `src/cache/__init__.py`

### 面试级知识点
- **语义缓存的核心原理**:将用户问题 embedding 后,在向量空间中查找相似的历史问题。若相似度超过阈值(如 0.95),则认为语义相同,直接返回缓存答案。
- **GPTCache 等开源方案**:GPTCache 是专为 LLM 设计的语义缓存框架,提供了完整的"embedding → 向量存储 → 相似度匹配 → 缓存返回"流程。理解其架构(Pre-Processor、Embedding、Vector Store、Cache Manager、Post-Processor)是面试加分项。
- **语义缓存的精度-召回权衡**:阈值越高(0.98),缓存精度高(不易答错),但召回率低;阈值越低(0.90),命中率高但可能返回不准确的缓存答案。需在评估中调优阈值。
- **语义缓存的适用场景**:用户问题多为开放式、变体多(如"怎么创建 Agent?" vs "Agent 如何构建?"),语义缓存效果显著;若用户问题多为精确查询(如"某函数的参数"),精确缓存已足够。

### 生产级注意事项
- **GPTCache 的集成方式**:使用 GPTCache 的 `LangChainCache` 适配器,无缝替换 LangChain 的默认缓存。
  ```python
  from gptcache import cache
  from gptcache.adapter.langchain_models import LangChainLLMs
  cache.init(pre_embedding_func=embedding_func)
  cached_llm = LangChainLLMs(llm=original_llm)
  ```
- **相似度阈值调优**:通过评估数据集,绘制"阈值 vs 答案正确率"曲线,选择保持 95% 正确率下的最高阈值。评估脚本应支持自动化调参。
- **缓存存储的向量库选择**:语义缓存需要向量库存储历史问题 embedding。可复用本项目的 Chroma(新建独立 collection),或使用轻量的 FAISS 内存索引。
- **缓存失效的复杂性**:知识库更新后,语义缓存可能返回过时答案。需实现基于文档版本的缓存版本控制:每次 `load_data.py` 重建向量库时,清空语义缓存。
- **避免缓存雪崩**:高并发场景下,大量请求同时触发未命中的相同查询,导致 LLM 被瞬间打爆。解决方法:① 请求合并(相同查询只调用一次 LLM);② 互斥锁(首个请求构建缓存,后续等待)。

### 验收标准
- 集成 GPTCache 并配置为 LangChain 的缓存后端,embedding 复用本项目的 Embedding 模型。
- 设置相似度阈值为 0.95,测试场景:先问"如何在 LangChain 中创建 Agent?",再问"LangChain 里 Agent 怎么构建?",验证第二次命中语义缓存,日志显示 `semantic_cache_hit=True`。
- 编写评估脚本:使用 Phase 3 的 QA pairs 测试不同阈值下的缓存命中率和答案准确率,生成调优报告(`data/eval/semantic_cache_tuning.md`)。
- 缓存存储使用 Chroma 的独立 collection(`semantic_cache`),重启应用后缓存仍有效。
- 文档化语义缓存的设计决策:为何选择 GPTCache、阈值调优过程、生产环境监控指标。
