## Task 1.10 依赖倒置修复与检索器接口抽象

### 任务目标
引入 `RetrieverProtocol` 协议类，使 `RAGChain` 依赖抽象接口而非具体 `VectorRetriever`，实现消费侧的依赖倒置；同时修复 `base_retriever.py` 和 `rag_chain.py` 中残余的直接导入具体实例问题，确保所有依赖通过参数注入或工厂函数获取。

### 涉及文件
- 新增 `src/retriever/protocols.py`
- 修改 `src/generation/rag_chain.py`
- 修改 `src/retriever/base_retriever.py`
- 修改 `src/evaluation/retrieval_eval.py`

### 面试级知识点
- **Protocol vs ABC**：`typing.Protocol` 定义结构子类型（Structural Subtyping），任何实现了所需方法的类自动符合协议，无需显式继承。这是 Python 鸭子类型的静态化表达。与 ABC 的区别：ABC 要求显式继承（_nominal subtyping_），Protocol 只要求方法签名匹配（_structural subtyping_）。
- **依赖倒置原则（DIP）**：高层模块（`RAGChain`）不应依赖低层模块（`VectorRetriever`），二者都应依赖抽象（`RetrieverProtocol`）。这是 SOLID 中最常被违反的原则，也是最难正确应用的原则。
- **类型标注的协变与逆变**：Protocol 支持更灵活的类型检查，无需修改现有类的继承树。理解为什么 `VectorRetriever` 无需任何代码修改就能满足 `RetrieverProtocol`。

### 生产级注意事项
- **隐式实现**：`VectorRetriever` 无需修改代码，因其已实现 `invoke` 方法，自动满足协议。这是 Protocol 的核心优势——非侵入式抽象。
- **异常声明**：在 Protocol 的 docstring 中声明预期可能抛出的异常类型（如 `RetrievalError`），供调用方参考。这是接口契约的一部分，缺失会导致调用方无法正确处理异常。
- **多态检索器预留**：未来可轻松接入 `ElasticsearchRetriever`、`MultiQueryRetriever` 或 `MockRetriever`，无需修改 `RAGChain`。这是依赖倒置的直接收益。
- **静态检查友好**：IDE 和类型检查器（如 mypy）能正确识别协议兼容性，提升重构安全性。
- **evaluation 模块同步**：`RetrievalEvaluator` 的 `retriever` 参数类型标注应更新为 `RetrieverProtocol`，保持类型系统一致性。

### Phase 2 复用策略
本 Task 建立的抽象层在 Phase 2 中的复用关系：
- ✅ **复用**：`RetrieverProtocol`（Phase 2 检索节点的 `retriever` 参数类型）、`VectorRetriever` 具体实现（Phase 2 检索节点直接调用 `retriever.invoke()`，不经过 RAGChain）、`format_docs()` 函数（Phase 2 生成节点复用文档格式化逻辑）
- ❌ **不复用**：`RAGChain` 的检索编排逻辑（Phase 2 检索节点直接调用 retriever，不走 RAGChain.invoke()）

### 验收标准
- 新增 `src/retriever/protocols.py`，定义 `RetrieverProtocol`，包含 `invoke(self, query: str) -> List[Document]` 方法签名及完整 docstring（含异常声明）。
- 修改 `RAGChain.__init__` 的 `retriever` 参数类型标注从 `VectorStoreRetriever` 改为 `RetrieverProtocol`。
- 修改 `src/evaluation/retrieval_eval.py` 中 `RetrievalEvaluator.__init__` 的 `retriever` 参数类型标注为 `RetrieverProtocol`。
- `base_retriever.py` 中不再有任何 `from src.core.config import ...` 语句，所有依赖通过参数注入。
- 运行现有 CLI，功能无任何退化。
- 编写一个测试：传入自定义 `MockRetriever`（未继承任何类，仅有 `invoke` 方法），验证 `RAGChain` 可正常调用检索。
