## Task 3.7 评估结果驱动的策略固化

### 任务目标
基于 Phase 3 的全部评估数据，做出数据驱动的架构决策——确定最终生产配置（默认使用哪种检索策略、是否启用 Reranker、MultiQuery 是否作为 fallback 等），并固化到配置文件和 LangGraph 工作流中。

### 涉及文件
- `src/core/config.py`（新增 `RetrievalStrategy` 枚举）
- `src/workflow/builder.py`（支持策略配置）
- `docs/retrieval_strategy_decision.md`（决策文档）

### 面试级知识点
- **数据驱动决策的面试话术**：“我们建立了完整的评估体系，对比了 Base、MultiQuery、HyDE、Ensemble 四种策略。数据显示 Ensemble 在 Context Recall 上领先 23%，但延迟增加 150ms；MultiQuery 在模糊问题上 Hit Rate 提升 12%，延迟增加 300ms。最终我们选择 Ensemble + Reranker 的组合，在精度和延迟间取得最佳平衡。”
- **策略组合的架构设计**：如何让系统支持运行时切换策略？通过配置枚举 + 工厂模式，在 `build_graph` 时注入不同的 `retriever_factory`。
- **成本-收益分析**：每种策略的边际成本（额外 LLM 调用次数、Token 消耗、延迟增量）vs 边际收益（评估指标提升）。

### 生产级注意事项
- **策略配置的代码实现**：
  ```python
  class RetrievalStrategy(str, Enum):
      BASE = "base"
      MULTI_QUERY = "multi_query"
      HYDE = "hyde"
      ENSEMBLE = "ensemble"
  
  def get_retriever(strategy: RetrievalStrategy) -> BaseRetriever:
      if strategy == RetrievalStrategy.BASE:
          return BaseVectorRetriever(...)
      elif strategy == RetrievalStrategy.ENSEMBLE:
          return EnsembleRetriever(...)
      ...
  ```
- **运行时策略切换**：通过环境变量 `RAG_RETRIEVAL_STRATEGY` 控制，便于不同环境（开发/测试/生产）使用不同策略。
- **Fallback 链设计**：文档评估节点判定不相关后，是否切换到备选策略（如 Base → MultiQuery → Tavily Search）？这是 Phase 4 的前置工作，现在可在路由逻辑中预留接口。
- **决策文档的重要性**：生产级项目必须有书面决策记录，解释“为什么选 A 不选 B”，供后续维护者和面试官理解。

### 验收标准
- 在 `config.py` 中定义 `RetrievalStrategy` 枚举和 `get_retriever(strategy)` 工厂函数。
- LangGraph 工作流支持通过环境变量切换检索策略，无需修改图结构代码。
- 编写 `docs/retrieval_strategy_decision.md`，包含：4 种策略的对比表格、性能数据、成本分析、最终决策及理由。
- 运行 `python src/evaluation/compare.py --all` 一键对比所有已实现策略，生成综合性对比报告。
- 端到端测试通过：使用最终选定的策略完成 5 轮多轮对话，验证功能完整性和答案质量。
