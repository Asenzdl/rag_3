## Task 1.9 配置管理与工厂重构

### 任务目标
彻底解耦配置读取与对象实例化，消除 `config.py` 模块导入时的副作用，建立符合 12-Factor App 规范的配置管理体系，为 Phase 2 多模型/多检索器切换奠定基础。同时确保向量库后端可配置化，实现消费侧和生产侧的完整抽象，支持通过环境变量无痛切换向量库。

### 涉及文件
- 新增 `src/core/settings.py`
- 新增 `src/core/factories.py`
- 修改 `src/core/config.py`
- 修改 `src/core/__init__.py`
- 修改 `src/retriever/base_retriever.py`
- 修改 `src/generation/rag_chain.py`
- 修改 `src/app.py`
- 修改 `src/evaluation/retrieval_eval.py`

### 面试级知识点
- **Pydantic BaseSettings 优先级机制**：环境变量 > `.env` 文件 > 默认值，通过 `model_config` 配置。为什么比 `os.getenv()` 更好：类型安全、自动校验、IDE 补全、文档即代码。
- **配置对象单例模式**：模块级实例化后全局复用，避免重复读取文件。与模块级副作用的区别：单例是显式创建，副作用是隐式触发。
- **工厂方法模式**：将对象创建过程封装，调用方只需指定类型，无需了解构造细节。开闭原则的体现：新增 LLM 提供商只需新增工厂函数，不修改调用方。
- **惰性实例化**：工厂函数延迟创建对象，避免模块导入时的副作用，提升启动速度，降低测试隔离成本。
- **12-Factor App 原则**：配置与代码严格分离，同一份构建物可通过环境变量部署到不同环境。
- **VectorStore 抽象基类**：LangChain 的 `VectorStore` 是所有向量库的抽象基类，`Chroma`、`FAISS`、`Pinecone` 等都是其子类。工厂函数返回 `VectorStore` 而非具体类型，是依赖倒置在数据层的体现。

### 生产级注意事项
- **敏感信息保护**：API Key 等字段应在 `Field` 中设置 `repr=False`，防止日志打印时泄露。
- **配置校验**：在 `Settings` 类中使用 `@field_validator` 确保必填字段非空，启动时快速失败而非运行时崩溃。
- **配置分组**：将 LLM 配置、检索配置、检查点配置分别定义为嵌套 Model，保持 `Settings` 类清晰。
- **单例缓存**：对于向量库连接和 Embedding 模型，在工厂函数内部使用 `@lru_cache` 缓存实例，避免重复初始化。
- **配置驱动创建**：工厂函数接收 `settings` 对象，根据配置动态决定创建何种类型的对象。
- **向量库后端可配置化**：`create_vectorstore()` 返回 `VectorStore` 抽象类型而非 `Chroma` 具体类型，通过 `vectorstore_type` 配置字段决定创建哪种向量库实现。迁移路径：改一个环境变量 → 工厂自动创建对应的 VectorStore → 消费侧无感切换。

### Phase 2 复用策略
本 Task 建立的基础设施在 Phase 2 中的复用关系：
- ✅ **复用**：`Settings` 类（Phase 2 节点通过 settings 获取 LLM/Embedding 实例）、`factories.py` 工厂函数（Phase 2 builder 中组装依赖）、`VectorStore` 抽象返回类型（Phase 2 检索节点无感切换向量库）
- ❌ **不复用**：`RAGChain` 编排逻辑（Phase 2 由 LangGraph StateGraph 取代编排角色，节点函数直接调用底层组件）

### 验收标准
- 新增 `src/core/settings.py`，包含 `Settings` 类，涵盖所有硬编码配置项：
  - API Key：`deepseek_api_key`、`qwen_api_key`、`tavily_api_key`
  - Base URL：`deepseek_base_url`、`qwen_base_url`、`ollama_base_url`（默认 `http://localhost:11434`）
  - 向量库配置：`vectorstore_type`（默认 `"chroma"`，为后续迁移预留）、`chroma_persist_directory`（默认 `db/langchain_docs_db1`）、`chroma_collection_name`（默认 `langchain_docs1`）
  - Embedding 模型：`embedding_model`（默认 `qwen3-embedding:4b`）
  - 评估路径：`eval_qa_path`、`eval_report_path`
  - 检查点路径：`checkpoint_db_path`（默认 `db/checkpoints.db`，为 Phase 2 预留）
- 新增 `src/core/factories.py`，包含以下工厂函数：
  - `create_embeddings(settings: Settings) -> Embeddings`
  - `create_vectorstore(settings: Settings, embedding_function: Embeddings) -> VectorStore`（注意返回 `VectorStore` 抽象类型，而非 `Chroma` 具体类型）
  - `create_retriever(settings: Settings, search_type: str, search_kwargs: Optional[Dict]) -> VectorRetriever`
  - `create_llm(provider: str, settings: Settings) -> BaseChatModel`
- 删除 `config.py` 中所有对象实例化代码（`init_chat_model`、`OllamaEmbeddings`），仅保留 `load_dotenv()` 和 `Settings` 实例导出。
- 修改 `core/__init__.py`：导出 `Settings` 类和工厂函数，不再导出具体 LLM/Embedding 实例。
- `base_retriever.py` 中的 `get_vectorstore()` 和 `create_vector_retriever()` 改为接收 `embeddings` 参数（依赖注入），不再从 config 导入 `ollama_embeddings`。
- `rag_chain.py` 删除 `from src.core.config import deepseek_llm` 导入，删除 `create()` 类方法。
- `app.py` 中显式调用工厂函数组装依赖，替代 `RAGChain.create()`。
- `retrieval_eval.py` 中的硬编码路径改为从 `Settings` 读取。
- 运行 `python src/app.py` 能正常启动，所有依赖模块从 `settings` 对象读取配置。
- 单元测试可通过 `Settings(_env_file=".env.test")` 注入测试配置，导入 `src.core.settings` 不触发任何网络请求或外部服务连接。
- 环境变量缺失时，`Settings` 实例化即抛出 `ValidationError`，而非延迟到运行时。
