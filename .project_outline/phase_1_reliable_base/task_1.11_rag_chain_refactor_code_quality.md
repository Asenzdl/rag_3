## Task 1.11 RAGChain 方法拆分与代码质量改善

### 任务目标
将 `RAGChain.invoke()` 的 150 行单体方法拆分为私有步骤方法，改善代码可读性和可维护性；修复 `ainvoke()` 假异步问题；同时完成 `citation_chain.py` 的代码质量改善。

**前置依赖**：Task 1.10（本 Task 在 1.10 修改过的 `rag_chain.py` 上继续工作，方法拆分需基于新的依赖注入接口）

**定位澄清**：本 Task 的核心目标是代码质量改善，而非为 LangGraph 节点映射做准备。Phase 2 的 LangGraph 节点函数将直接调用底层组件（retriever、LLM、CitationExtractor），不经过 RAGChain 的编排逻辑。RAGChain 在 Phase 2 中仍作为 Phase 1 CLI 的入口保留，但其编排角色将被 LangGraph StateGraph 取代。

### 涉及文件
- 修改 `src/generation/rag_chain.py`
- 修改 `src/generation/citation_chain.py`
- 修改 `src/evaluation/dataset.py`

### 面试级知识点
- **God Method 反模式**：单体方法（超过 50 行、承担多个职责的方法）是面向对象中最常见的反模式。将编排逻辑与步骤实现分离后，每个步骤可独立阅读、独立测试。但需注意拆分粒度——过度拆分为独立函数会引入不必要的间接层，私有方法是更温和的替代方案。
- **私有方法 vs 独立函数**：当步骤函数仅在类内部使用、不需要跨模块复用时，私有方法（`_step_name`）比独立函数更合适——它保持了类的内聚性，避免了模块级函数爆炸。独立函数适用于需要跨模块复用或与外部框架集成的场景。
- **假异步的危害**：`async def` 中调用同步阻塞函数会阻塞事件循环，导致所有协程挂起。这比 `NotImplementedError` 更危险，因为调用方无法从类型签名判断行为是否真正异步。

### 生产级注意事项
- **拆分粒度选择**：采用私有方法而非独立函数，原因：
  - 步骤函数仅在 `RAGChain` 内部使用，Phase 2 不会复用这些步骤函数（LangGraph 节点直接调用底层组件）
  - 私有方法保持了类的内聚性，避免模块级函数爆炸
  - 独立函数适用于需要跨模块复用的场景（如 `format_docs()` 已是独立函数，Phase 2 生成节点可复用）
- **invoke() 改为编排方法**：拆分后 `invoke()` 仅负责调用私有步骤方法并组装结果，逻辑应简洁清晰（不超过 30 行）。
- **stream() 的拆分策略**：`_retrieve_step()` 可在 `stream()` 中复用（无副作用），但生成步骤因流式语义不同（yield vs return）应保持独立实现，不强求共享私有方法。
- **ainvoke() 占位合规**：标记为 `raise NotImplementedError`，docstring 注明"当前为占位，Task 4.5 应独立评估"。禁止假异步实现。
- **异常处理统一**：`retrieve()` 和 `invoke()` 中的检索异常处理应统一策略——私有步骤方法中保留原始异常语义（`RetrievalError`），在编排层（`invoke()`）统一转换为 `GenerationError`。

### Phase 2 复用策略
本 Task 修改的模块在 Phase 2 中的定位：
- ✅ **复用**：`format_docs()` 独立函数（Phase 2 生成节点直接调用）、`CitationExtractor`（Phase 2 引用提取节点直接调用）、`RAGResponse` 数据结构（Phase 2 可作为最终输出格式）
- ❌ **不复用**：`RAGChain.invoke()` 编排逻辑（Phase 2 由 LangGraph StateGraph 取代）、`RAGChain.stream()` 流式逻辑（Phase 2 由 LangGraph `graph.stream()` 取代）、私有步骤方法（Phase 2 节点直接调用底层组件）
- 📌 **保留**：`RAGChain` 类本身在 Phase 2 过渡期仍作为 CLI 入口保留，直到 Phase 2 CLI 升级（Task 2.7）完成后可逐步废弃

### 验收标准

#### RAGChain 方法拆分
- 将 `invoke()` 中的检索、空检索拦截、生成、引用提取步骤提取为私有方法（如 `_retrieve_step()`、`_generate_step()`、`_extract_citations_step()`），`invoke()` 改为调用私有方法的编排方法，逻辑不超过 30 行。
- `retrieve()` 方法与 `invoke()` 中的检索步骤使用相同的私有方法，消除异常处理逻辑重复。
- `stream()` 方法复用 `_retrieve_step()`，生成步骤保持独立实现。
- `ainvoke()` 抛出 `NotImplementedError`，docstring 注明"当前为占位，Task 4.5 应独立评估"。

#### 质量保障
- 运行 `python src/run.py` 功能无退化。
- 运行 `python src/evaluation/retrieval_eval.py`，Hit Rate@5 与重构前偏差 < 1%。
