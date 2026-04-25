# Task 1.10 配置管理、工厂模式与检索器协议抽象 - 架构设计

> **原始需求**：`.project_outline/phase_1_reliable_base/task_1.10_config_factory_protocol.md`
> **涉及文件**：`src/core/settings.py`、`src/core/factories.py`、`src/retriever/protocols.py`、`src/core/config.py`、`src/core/__init__.py`、`src/retriever/base_retriever.py`、`src/retriever/__init__.py`、`src/generation/rag_chain.py`、`src/generation/__init__.py`、`src/app.py`、`src/evaluation/retrieval_eval.py`

---

## 架构决策与权衡

### 决策 1：Pydantic BaseSettings vs 手动 os.getenv + dotenv

- **设计原则**：配置管理外部化、类型安全
- **选项 A**：继续使用 `os.getenv()` + `load_dotenv()`，在各模块直接读取 — 优点：简单直接、零依赖；缺点：无类型校验（Key 拼错运行时才爆）、无 IDE 补全、API Key 泄露风险（`print(config)` 可见）、默认值散落各处无法集中审视
- **选项 B**：Pydantic BaseSettings + `.env` 文件 — 优点：类型安全 + 自动校验 + `repr=False` 防泄露 + IDE 补全 + 启动时快速失败 + 配置集中定义；缺点：引入 `pydantic-settings` 依赖、需学习 `model_config` 机制
- **结论**：选 B。项目已大量使用 Pydantic（LangChain 生态强依赖），无额外依赖成本。`os.getenv` 的散落式配置正是当前 `config.py` 的核心痛点——3 个 API Key + 硬编码 URL 散布，修改一处需检查全局。
- **技术文档展开方向**：讲透 Pydantic BaseSettings 的优先级机制（环境变量 > .env > 默认值）与 `@field_validator` 启动时校验

### 决策 2：Protocol vs ABC 定义检索器协议

- **设计原则**：依赖倒置、开闭原则
- **选项 A**：ABC（`RetrieverProtocol(ABC)` + `@abstractmethod`）— 优点：显式继承关系、IDE 可跳转到基类；缺点：`VectorRetriever` 必须显式继承 `RetrieverProtocol`，侵入式修改；与 LangChain 的 `VectorStoreRetriever` 多继承时可能 MRO 冲突
- **选项 B**：`typing.Protocol`（结构子类型）— 优点：`VectorRetriever` 无需修改代码（已实现 `invoke` 方法即自动满足协议）、非侵入式抽象、与 LangChain 类型系统无冲突；缺点：无显式继承关系，IDE 跳转不如 ABC 直观（可用 `@runtime_checkable` 弥补）
- **结论**：选 B。Protocol 的核心优势——非侵入式抽象，恰好解决当前痛点：`VectorRetriever` 继承自 LangChain 的 `VectorStoreRetriever`，强行加 ABC 继承既侵入又有 MRO 风险。Protocol 只看方法签名，不需要修改已有代码，这是 Go/Rust 社区的主流实践。
- **技术文档展开方向**：讲透 Protocol vs ABC 的本质区别（结构子类型 vs 名片子类型），以及各自的最佳适用场景

### 决策 3：工厂函数 vs 工厂类

- **设计原则**：简单性、KISS
- **选项 A**：工厂类（`LLMFactory`、`RetrieverFactory`）— 优点：可维护内部状态、支持注册机制；缺点：当前只需 4 个工厂函数，工厂类是过度设计
- **选项 B**：模块级工厂函数 + `@lru_cache` — 优点：简单直接、`lru_cache` 天然提供单例缓存、函数签名即文档；缺点：无法维护复杂状态（但当前不需要）
- **结论**：选 B。当前只有 DeepSeek + Qwen 两个 LLM 提供商和 Chroma 一个向量库，4 个工厂函数足够。若 Phase 4 需要动态注册新提供商，再迁移到注册式工厂。
- **技术文档展开方向**：讲透工厂方法模式从函数到类的演进路径，以及 `@lru_cache` 单例模式的陷阱

### 决策 4：config.py 的命运——删还是留？

- **设计原则**：模块分离、向前兼容
- **选项 A**：完全删除 `config.py` — 优点：无冗余；缺点：所有 `from src.core.config import ...` 的调用点都需要一次性改完，风险大
- **选项 B**：保留 `config.py` 但清空所有实例化代码，仅保留 `load_dotenv()` + `settings` 实例导出 — 优点：渐进式迁移、`config.py` 变为"配置入口门面"；缺点：多一层间接（但语义清晰）
- **结论**：选 B。`config.py` 职责变为"加载 .env + 导出 settings 单例"，所有消费方逐步改为从 `settings` 读取或通过工厂函数获取对象。这符合"配置集中化"的 12-Factor 原则。

---

## 设计约束与假设

### 外部约束
- `pydantic-settings` 需作为新依赖安装（`pip install pydantic-settings`）
- Pydantic v2 的 `BaseSettings` 已从 `pydantic` 迁移到 `pydantic-settings` 包
- LangChain 的 `init_chat_model` 接受 `api_key`/`base_url` 参数，工厂函数需透传 Settings 中的对应字段
- `OllamaEmbeddings` 的 `base_url` 默认值为 `http://localhost:11434`，需与 Settings 中的 `ollama_base_url` 默认值一致

### 设计假设
- 当前只有 2 个 LLM 提供商（DeepSeek、Qwen），`create_llm(provider=...)` 用 if-elif 足够；超过 5 个时考虑注册式工厂
- 当前只有 Chroma 一个向量库后端，`create_vectorstore()` 的 `vectorstore_type` 仅支持 `"chroma"`；FAISS/Pinecone 支持在 Phase 3+ 按需添加
- `VectorRetriever` 的 `invoke(self, query: str) -> List[Document]` 方法签名已存在且稳定，Protocol 定义与之匹配

### 隐含前提
- `load_dotenv()` 必须在任何 `Settings()` 实例化之前调用，否则 `.env` 文件中的值不会被环境变量加载
- 工厂函数的 `@lru_cache` 需注意：若 Settings 对象不是 hashable 的（Pydantic v2 的 BaseModel 默认是 frozen=False 不可 hash），需要将工厂函数设计为接收 Settings 参数但不缓存 Settings 本身，而是缓存工厂创建的对象实例
- `RAGChain.create()` 类方法删除后，`app.py` 需改用 `create_rag_chain(settings)` 替代

---

## 模块结构

### 文件组织
```
src/core/
├── __init__.py      # 导出 Settings、工厂函数、异常类
├── config.py        # 仅保留 load_dotenv() + settings 实例导出
├── settings.py      # [新增] Pydantic BaseSettings 配置类
├── factories.py     # [新增] 工厂函数（create_embeddings/create_vectorstore/create_retriever/create_llm/create_rag_chain）
└── exceptions.py    # 异常体系（不变）

src/retriever/
├── __init__.py      # 导出增加 RetrieverProtocol
├── protocols.py     # [新增] RetrieverProtocol 定义
└── base_retriever.py  # 修改：依赖注入 embeddings 参数
```

### 关键外部依赖
```
settings.py
├── pydantic_settings   # BaseSettings 基类（v2 从 pydantic 分离出来）
├── pydantic            # Field, field_validator, model_config

factories.py
├── langchain.chat_models.init_chat_model  # 统一 LLM 初始化接口
├── langchain_ollama.OllamaEmbeddings      # Ollama 嵌入模型
├── langchain_chroma.Chroma               # Chroma 向量库
├── langchain_core.vectorstores.VectorStore  # 向量库抽象基类
├── langchain_core.language_models.BaseChatModel  # LLM 抽象基类
```

### 职责边界

```
settings.py 职责：
✅ 包含：所有配置项的定义（API Key、URL、路径、模型名）
✅ 包含：Pydantic BaseSettings 的 model_config 配置
✅ 包含：field_validator 校验逻辑
❌ 不包含：任何对象实例化代码（LLM/Embedding/VectorStore 的创建）← 属于 factories.py
❌ 不包含：业务逻辑 ← 属于各业务模块

factories.py 职责：
✅ 包含：工厂函数（create_embeddings/create_vectorstore/create_retriever/create_llm/create_rag_chain）
✅ 包含：@lru_cache 单例缓存
✅ 包含：对象创建的日志记录
❌ 不包含：配置定义 ← 属于 settings.py
❌ 不包含：业务编排逻辑 ← 属于 RAGChain / LangGraph

protocols.py 职责：
✅ 包含：RetrieverProtocol 定义（方法签名 + docstring + 异常声明）
❌ 不包含：Protocol 的具体实现 ← 由 VectorRetriever 等类隐式实现
❌ 不包含：检索业务逻辑 ← 属于 base_retriever.py

config.py 重构后职责：
✅ 包含：load_dotenv(override=True) 调用
✅ 包含：settings 单例实例导出
❌ 不包含：任何 LLM/Embedding 实例化代码 ← 迁移到 factories.py
```

---

## 契约速览

### settings.py

```python
class Settings(BaseSettings):  # P0
    """12-Factor App 配置管理 — 类型安全 + 启动校验 + 防泄露。"""
    # API Keys（repr=False）
    deepseek_api_key: str
    qwen_api_key: str
    tavily_api_key: str = ""
    # Base URLs
    deepseek_base_url: str
    qwen_base_url: str
    ollama_base_url: str = "http://localhost:11434"
    # 向量库配置
    vectorstore_type: str = "chroma"
    chroma_persist_directory: str = "db/langchain_docs_db1"
    chroma_collection_name: str = "langchain_docs1"
    # Embedding
    embedding_model: str = "qwen3-embedding:4b"
    # 评估路径
    eval_qa_path: str = "data/eval/qa_pairs.json"
    eval_report_path: str = "data/eval/baseline_retrieval_report.md"
    # 检查点路径（Phase 2 预留）
    checkpoint_db_path: str = "db/checkpoints.db"

    model_config: ClassVar[SettingsConfigDict] = ...

class LLMConfig(BaseModel):  # P2
    """LLM 提供商配置分组（嵌套 Model）。"""
    provider: str
    model: str
    api_key: str
    base_url: str
    streaming: bool = False
    temperature: float = 0
```

### factories.py

```python
def create_embeddings(settings: Settings) -> Embeddings:  # P0
    """根据 settings 创建 Ollama Embeddings 实例（@lru_cache 缓存）。"""

def create_vectorstore(settings: Settings, embedding_function: Embeddings) -> VectorStore:  # P0
    """根据 settings 创建向量库实例（返回 VectorStore 抽象类型，@lru_cache 缓存）。"""

def create_retriever(settings: Settings, search_type: str = "similarity", search_kwargs: Optional[Dict] = None) -> RetrieverProtocol:  # P0
    """根据 settings 创建检索器实例（返回 RetrieverProtocol 协议类型）。"""

def create_llm(provider: str, settings: Settings) -> BaseChatModel:  # P1
    """根据 provider 和 settings 创建 LLM 实例（@lru_cache 缓存）。"""

def create_rag_chain(settings: Settings) -> RAGChain:  # P0
    """一行创建完整 RAGChain（封装检索器 + LLM + Prompt 的组装逻辑）。"""
```

### protocols.py

```python
class RetrieverProtocol(Protocol):  # P0
    """检索器协议 — 结构子类型，任何实现了 invoke 方法的类自动满足。"""
    def invoke(self, query: str) -> List[Document]: ...
```

---

## 错误处理策略

### 异常捕获与包装策略

| 异常类型 | 捕获位置 | 包装为 | 是否中断主流程 | 理由 |
|---------|---------|-------|-------------|------|
| `ValidationError` | `Settings()` 实例化时 | 不包装，直接上抛 | 是 | 配置缺失/格式错误应在启动时快速失败 |
| `ValueError` | `create_vectorstore()` Chroma 初始化 | `RetrievalError` | 是 | 向量库连接失败无法继续 |
| `ValueError` | `create_llm()` 不支持的 provider | `NonRetryableError` | 是 | 配置错误，重试无意义 |
| `ImportError` | `create_vectorstore()` 不支持的 vectorstore_type | `NonRetryableError` | 是 | 向量库驱动未安装 |

### 可恢复 vs 不可恢复的判定
- **不可恢复**（中断并上抛）：Settings 校验失败（ValidationError）、不支持的 LLM provider、不支持的向量库类型
- **不适用可恢复场景**：工厂函数是创建时一次性操作，不存在"部分失败后继续"的场景

### 骨架引用规则
骨架步骤注释中使用 `# 按异常策略表第 N 行处理` 引用本表。

---

## 代码骨架

### settings.py

```python
class LLMConfig(BaseModel):  # P2
    """LLM 提供商配置分组。

    为什么用嵌套 Model 而非平铺字段：
        当前有 DeepSeek 和 Qwen 两个提供商，每个有 api_key + base_url + model。
        若平铺为 deepseek_api_key/deepseek_base_url/... 会导致 Settings 类字段爆炸。
        嵌套 Model 让每个提供商的配置内聚，新增提供商只需添加一个 LLMConfig 字段。

    为什么不把 LLMConfig 放到 Settings 的嵌套字段中（本次不采用）：
        .env 文件中的命名规则 — Pydantic 嵌套 Model 需要 DEEPSEEK__API_KEY 双下划线前缀，
        与当前 .env 中的 DEEPSEEK_API_KEY 不兼容，迁移成本高。
        因此本次仍使用平铺字段 + 前缀分组的方式，后续可迁移为嵌套结构。
    """
    # provider 字段（如 "deepseek"、"qwen"）
    # model 字段（如 "deepseek-chat"）
    # api_key 字段（repr=False）
    # base_url 字段
    # streaming 字段（默认 False）
    # temperature 字段（默认 0）


class Settings(BaseSettings):  # P0
    """12-Factor App 配置管理。

    为什么用 Pydantic BaseSettings 而非 os.getenv：
        1. 类型安全：API Key 必须是 str，端口必须是 int，启动时自动校验
        2. 防泄露：Field(repr=False) 防止日志/调试时打印明文 Key
        3. IDE 补全：settings.deepseek_api_key 比 os.getenv("DEEPSEEK_API_KEY") 更友好
        4. 文档即代码：每个 Field 的 description 就是配置文档
        5. 启动时快速失败：必填字段缺失时 ValidationError 立即报错，
           而非运行到 LLM 调用才发现 Key 为 None

    优先级机制：
        环境变量 > .env 文件 > Field 默认值
        这是 Pydantic BaseSettings 的核心特性，确保：
        - 本地开发：.env 文件提供默认配置
        - 生产部署：环境变量覆盖 .env（同一份构建物走不同环境）
    """

    # ===== API Keys（repr=False 防止日志泄露）=====
    # deepseek_api_key: str = Field(repr=False, description="DeepSeek API Key")
    # 为什么不设默认值：必填字段缺失时 Settings() 实例化即抛 ValidationError
    # qwen_api_key: str = Field(repr=False, description="Qwen API Key")
    # tavily_api_key: str = Field(default="", repr=False, description="Tavily 搜索 API Key（Phase 4）")
    # 为什么 default=""：Tavily 是 Phase 4 才用的，当前不应强制要求

    # ===== Base URLs =====
    # deepseek_base_url: str = Field(description="DeepSeek API Base URL")
    # qwen_base_url: str = Field(description="Qwen API Base URL")
    # ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama 服务地址")
    # 为什么默认 localhost:11434：Ollama 默认监听此端口

    # ===== 向量库配置 =====
    # vectorstore_type: str = Field(default="chroma", description="向量库类型（chroma/faiss/pinecone）")
    # chroma_persist_directory: str = Field(default="db/langchain_docs_db1", description="Chroma 数据目录")
    # chroma_collection_name: str = Field(default="langchain_docs1", description="Chroma 集合名称")

    # ===== Embedding 配置 =====
    # embedding_model: str = Field(default="qwen3-embedding:4b", description="Ollama Embedding 模型名")

    # ===== 评估路径 =====
    # eval_qa_path: str = Field(default="data/eval/qa_pairs.json", description="评估 QA 对路径")
    # eval_report_path: str = Field(default="data/eval/baseline_retrieval_report.md", description="评估报告输出路径")

    # ===== 检查点路径（Phase 2 预留）=====
    # checkpoint_db_path: str = Field(default="db/checkpoints.db", description="LangGraph 检查点数据库路径")

    # model_config 配置：
    #   env_file = ".env" — 指定 .env 文件路径
    #   env_file_encoding = "utf-8"
    #   extra = "ignore" — 忽略 .env 中未在 Settings 中定义的变量
    #   为什么 extra="ignore"：.env 可能有其他工具的变量（如 TAVILY_API_KEY 在 Phase 1 无意义），
    #     不应因此报错

    # @field_validator 校验：
    #   对 deepseek_api_key 和 qwen_api_key 校验非空非空白
    #   为什么需要：即使 str 类型无默认值会触发 ValidationError，
    #     但 .env 中可能设为空字符串（DEEPSEEK_API_KEY=""），需要 strip 后校验
    #   校验逻辑：去除首尾空白 → 若为空字符串 → 抛出 ValueError("xxx 不能为空")
```

### protocols.py

```python
class RetrieverProtocol(Protocol):  # P0
    """检索器协议 — 定义检索器的最小行为契约。

    为什么用 Protocol 而非 ABC：
        1. 非侵入式：VectorRetriever 继承自 LangChain 的 VectorStoreRetriever，
           强制它再继承 ABC 会引入多继承 MRO 问题。Protocol 只看方法签名，
           VectorRetriever 无需修改任何代码即自动满足协议。
        2. 鸭子类型的类型安全版：Protocol 是"结构子类型"——不关心类继承关系，
           只关心"有没有 invoke 方法且签名匹配"。这与 Python 的鸭子类型哲学一致，
           但增加了静态类型检查。
        3. 依赖倒置的最佳实践：RAGChain 依赖 RetrieverProtocol（抽象），
           而非 VectorRetriever（具体），新增检索器类型时无需修改 RAGChain。

    隐式实现验证：
        VectorRetriever._get_relevant_documents 的 override 方法 + VectorStoreRetriever.invoke
        → 签名为 invoke(self, query: str) -> List[Document]
        → 自动满足 RetrieverProtocol，无需显式声明

    异常声明（接口契约的一部分）：
        - RetrievalError: 检索过程中的通用异常
        - UnsupportedSearchTypeError: 不支持的搜索类型（NonRetryableError）

    注意点：
        Protocol 类本身不应有业务逻辑实现，仅定义方法签名和 docstring。
        @runtime_checkable 可选 — 允许 isinstance(obj, RetrieverProtocol) 运行时检查，
        但有性能开销且只检查方法存在性不检查签名。当前不需要 runtime_checkable。
    """

    def invoke(self, query: str) -> List[Document]:
        """执行检索并返回相关文档列表。

        Args:
            query: 用户查询字符串

        Returns:
            按相关性排序的文档列表

        Raises:
            RetrievalError: 检索过程中发生异常
            UnsupportedSearchTypeError: 搜索类型不被支持
        """
        ...
```

### factories.py

```python
# create_embeddings(settings: Settings) -> Embeddings  # P0
# """根据 settings 创建 Ollama Embeddings 实例。

# 为什么用 @lru_cache 而非模块级变量：
#     模块级变量在 import 时就创建实例（副作用），而 @lru_cache 延迟到首次调用时创建（惰性）。
#     惰性实例化的好处：导入 settings 模块不会触发网络请求或模型加载，
#     测试时可以安全导入而不担心连接外部服务。

# 为什么缓存：OllamaEmbeddings 初始化会加载模型（耗时较长），
#     多次创建同一配置的实例浪费资源。

# 步骤 1：创建 OllamaEmbeddings 实例
#   传入 model=settings.embedding_model
#   传入 base_url=settings.ollama_base_url
# 步骤 2：记录 info 日志（模型名、base_url）
# 步骤 3：返回实例
# """

# 注意：@lru_cache 要求参数可 hash。Settings 是 Pydantic BaseModel，
# 默认 frozen=False 不可 hash。解决方案：工厂函数不缓存 Settings 参数，
# 而是将 @lru_cache 用在无参的内部函数上，通过闭包或模块级变量访问 settings。
# 最终方案：工厂函数不接收 settings 参数，而是从 config 模块获取 settings 单例。
# 但这违反了"配置驱动创建"的原则...
#
# 实际解决方案：工厂函数接收 settings 参数，但内部不使用 @lru_cache。
# 单例缓存由 get_vectorstore 的 @lru_cache 提供（已有机制）。
# create_embeddings 的单例通过模块级 _embeddings_cache: Optional[Embeddings] = None 实现，
# 首次调用时创建并缓存，后续调用直接返回。
# 这比 @lru_cache 更灵活——不要求 Settings 可 hash。


# create_vectorstore(settings: Settings, embedding_function: Embeddings) -> VectorStore  # P0
# """根据 settings 创建向量库实例（返回 VectorStore 抽象类型）。

# 为什么返回 VectorStore 而非 Chroma：
#     依赖倒置——调用方（检索器、评估器）依赖抽象类型，
#     后续切换为 FAISS/Pinecone 时调用方代码无需修改。

# 步骤 1：按异常策略表第 2 行处理 — 检查 settings.vectorstore_type
#   ├─ "chroma" → 创建 Chroma 实例
#   │   传入 persist_directory=settings.chroma_persist_directory
#   │   传入 collection_name=settings.chroma_collection_name
#   │   传入 embedding_function=embedding_function
#   └─ 其他值 → 抛出 NonRetryableError(f"不支持的向量库类型: {vectorstore_type}")
# 步骤 2：记录 info 日志（向量库类型、目录、集合名）
# 步骤 3：返回 VectorStore 实例
# """


# create_retriever(settings: Settings, search_type: str = "similarity", search_kwargs: Optional[Dict] = None) -> RetrieverProtocol  # P0
# """根据 settings 创建检索器实例（返回 RetrieverProtocol 协议类型）。

# 为什么返回 RetrieverProtocol 而非 VectorRetriever：
#     依赖倒置——消费方（RAGChain、RetrievalEvaluator）依赖协议而非具体类型，
#     新增检索器实现时无需修改消费方代码。

# 步骤 1：调用 create_embeddings(settings) 获取 embeddings 实例
# 步骤 2：调用 create_vectorstore(settings, embeddings) 获取 vectorstore 实例
# 步骤 3：调用原有 create_vector_retriever() 的逻辑创建 VectorRetriever
#   但需将 embeddings 参数注入到 get_vectorstore 中
#   具体做法：
#   - 设置 search_kwargs 默认值 {"k": 5}（若未提供）
#   - 创建 VectorRetriever(vectorstore=vectorstore, search_type=search_type, search_kwargs=kwargs)
# 步骤 4：记录 info 日志（search_type、search_kwargs）
# 步骤 5：返回检索器实例（类型标注为 RetrieverProtocol）
# """


# create_llm(provider: str, settings: Settings) -> BaseChatModel  # P1
# """根据 provider 和 settings 创建 LLM 实例。

# 为什么参数是 provider 字符串而非枚举：
#     字符串更灵活，后续新增提供商无需修改枚举定义。
#     但在工厂函数内部做校验，不支持的 provider 立即报错。

# 步骤 1：按异常策略表第 3 行处理 — 检查 provider
#   ├─ "deepseek" → 调用 init_chat_model
#   │   传入 model="deepseek-chat"
#   │   传入 model_provider="deepseek"
#   │   传入 api_key=settings.deepseek_api_key
#   │   传入 base_url=settings.deepseek_base_url
#   │   传入 streaming=True, temperature=0
#   ├─ "qwen" → 调用 init_chat_model
#   │   传入 model="qwen3.5-plus"
#   │   传入 model_provider="deepseek"（注意：Qwen 使用 DeepSeek 兼容协议）
#   │   传入 api_key=settings.qwen_api_key
#   │   传入 base_url=settings.qwen_base_url
#   └─ 其他值 → 抛出 NonRetryableError(f"不支持的 LLM 提供商: {provider}")
# 步骤 2：记录 info 日志（provider、model 名）
# 步骤 3：返回 BaseChatModel 实例
# """


# create_rag_chain(settings: Settings) -> RAGChain  # P0
# """一行创建完整 RAGChain — 封装检索器 + LLM + Prompt 的组装逻辑。

# 为什么不直接在 app.py 中组装：
#     1. 单一入口：所有消费方（app.py、测试、未来 FastAPI）统一走此函数
#     2. 配置驱动：settings 对象决定创建什么组件，调用方无需了解细节
#     3. 可测试性：测试可通过传入 Mock 的 settings 创建定制化 RAGChain

# 步骤 1：调用 create_retriever(settings) 获取 retriever
# 步骤 2：调用 create_llm("deepseek", settings) 获取 llm
# 步骤 3：调用 get_prompt(PromptVersion.V2, include_few_shot=True) 获取 prompt
# 步骤 4：创建 RAGChain(retriever=retriever, llm=llm, prompt=prompt)
# 步骤 5：记录 info 日志（各组件创建完成）
# 步骤 6：返回 RAGChain 实例
# """
```

### config.py（重构后）

```python
# config.py 重构为"配置入口门面"

# 步骤 1：保留 load_dotenv(override=True) — 确保环境变量加载
# 步骤 2：从 settings 模块导入 Settings 类
# 步骤 3：创建 settings 单例 — settings = Settings()
#   为什么在此实例化：load_dotenv 必须先于 Settings() 执行，
#   而 config.py 是最先被导入的核心模块，天然保证顺序
# 步骤 4：删除所有 LLM/Embedding 实例化代码
#   删除 init_chat_model 调用
#   删除 OllamaEmbeddings 实例化
#   删除 deepseek_llm、qwen_llm、ollama_embeddings 变量
# 步骤 5：删除 os.getenv 调用（已迁移到 Settings）
```

### base_retriever.py（修改）

```python
# 修改点 1：删除 from src.core.config import ollama_embeddings
# 修改点 2：get_vectorstore() 签名变更
#   新增参数：embedding_function: Embeddings
#   不再有默认值——调用方必须显式传入 embeddings 实例（依赖注入）
#   为什么：消除对 config.ollama_embeddings 的硬编码依赖，
#     使 get_vectorstore 可接收不同配置的 embeddings 实例

# 修改点 3：create_vector_retriever() 签名变更
#   新增参数：embedding_function: Embeddings
#   将 embedding_function 透传给 get_vectorstore()
#   其他参数和逻辑不变

# 修改点 4：返回类型标注不变（VectorRetriever）
#   为什么不改为 RetrieverProtocol：
#     base_retriever.py 的职责是"创建并返回 VectorRetriever 实例"，
#     返回具体类型更精确。Protocol 类型由 factories.py 的 create_retriever() 在调用层声明。
```

### rag_chain.py（修改）

```python
# 修改点 1：删除 from src.core.config import deepseek_llm
# 修改点 2：删除 RAGChain.create() 类方法（整体删除，约 60 行）
#   为什么：创建逻辑已迁移到 factories.create_rag_chain()
# 修改点 3：__init__ 的 retriever 参数类型标注
#   从 VectorStoreRetriever 改为 RetrieverProtocol
#   导入：from src.retriever.protocols import RetrieverProtocol
#   为什么：依赖倒置——RAGChain 依赖协议而非具体类型
# 修改点 4：模块级 docstring 更新
#   使用示例从 RAGChain.create() 改为 create_rag_chain(settings)
# 修改点 5：删除 from src.retriever.base_retriever import create_vector_retriever
#   RAGChain 不再直接创建检索器
# 修改点 6：from src.core.config import deepseek_llm 删除
```

### app.py（修改）

```python
# 修改点 1：删除 from src.generation.rag_chain import RAGChain
# 修改点 2：新增 from src.core.factories import create_rag_chain
# 修改点 3：新增 from src.core.config import settings
# 修改点 4：main() 中 chain = RAGChain.create() 改为 chain = create_rag_chain(settings)
# 修改点 5：删除 load_dotenv(override=True) — 已在 config.py 中调用
#   为什么删除：config.py 被导入时已执行 load_dotenv，
#   app.py 中再调用是冗余的。但保留也无害——load_dotenv 是幂等的。
#   决定：保留 load_dotenv(override=True)，因为 app.py 作为入口需显式确保环境变量就绪
#   这与原设计意图一致（参见 app.py main() 注释）
```

### retrieval_eval.py（修改）

```python
# 修改点 1：RetrievalEvaluator.__init__ 的 retriever 参数类型标注
#   从无类型标注改为 retriever: RetrieverProtocol
#   导入：from src.retriever.protocols import RetrieverProtocol
# 修改点 2：run_baseline_eval() 函数
#   硬编码路径 "data/eval/qa_pairs.json" 和 "data/eval/baseline_retrieval_report.md"
#   改为从 settings 读取
#   导入 settings：from src.core.config import settings
#   传入 settings.eval_qa_path 和 settings.eval_report_path
# 修改点 3：run_baseline_eval() 中创建检索器的方式
#   从 create_vector_retriever(search_kwargs={"k": search_k}) 改为
#   create_retriever(settings, search_kwargs={"k": search_k})
#   导入 create_retriever：from src.core.factories import create_retriever
```

---

## 常见坑点

1. **Pydantic BaseSettings 的 .env 加载时序**：`Settings()` 实例化时才读取 `.env` 文件，而 `load_dotenv()` 必须在此之前执行，否则环境变量不存在导致 `ValidationError`。解决方案：`config.py` 中先调 `load_dotenv()` 再创建 `settings = Settings()`。

2. **BaseModel 默认不可 hash 与 @lru_cache 不兼容**：Pydantic v2 的 `BaseModel` 默认 `frozen=False`，不能作为 `@lru_cache` 的参数。若工厂函数要缓存，需改用模块级变量或 `functools.cache` 包装无参内部函数。本项目采用模块级 `_cache: Optional[T] = None` 模式。

3. **Protocol 的运行时检查陷阱**：`@runtime_checkable` 装饰器只检查方法名存在性，不检查签名。一个 `invoke(self, x: int) -> str` 也满足 `isinstance(obj, RetrieverProtocol)`。因此在 Protocol 的 docstring 中明确声明异常类型，作为接口契约的补充。

4. **工厂函数的循环导入风险**：`factories.py` 需要导入 `RAGChain`（来自 `generation`），而 `generation` 可能间接导入 `core`。解决方案：`create_rag_chain()` 中使用延迟导入（函数内部 `from src.generation.rag_chain import RAGChain`），避免模块级循环依赖。

5. **Settings 必填字段与 .env 空字符串**：`Field()` 无默认值的 str 字段，若 `.env` 中设为 `DEEPSEEK_API_KEY=""`，Pydantic 会将其解析为空字符串而非触发缺失校验。需要 `@field_validator` strip 后检查非空。

---

## 测试策略概要

### Mock 边界
- **Settings**：测试中通过 `Settings(_env_file=".env.test")` 或直接传参注入测试配置
- **Embeddings/VectorStore/LLM**：通过工厂函数注入 Mock settings 创建 Mock 实例
- **RetrieverProtocol**：创建仅含 `invoke` 方法的 `MockRetriever`（无需继承任何类）

### 可独立测试的纯函数
- `Settings` 的 `field_validator` 校验逻辑
- `RetrieverProtocol` 的类型检查（`isinstance` 或 `cast`）

### 关键测试场景
- Settings 必填字段缺失时抛出 `ValidationError`
- Settings API Key 字段 `repr=False`（`repr(settings)` 不含明文 Key）
- `MockRetriever`（仅有 `invoke` 方法）传入 `RAGChain` 可正常调用检索
- `create_llm("deepseek", settings)` 返回正确配置的 LLM 实例
- `create_llm("unsupported", settings)` 抛出 `NonRetryableError`
- `create_vectorstore(settings, embeddings)` 返回 `VectorStore` 抽象类型
- `create_rag_chain(settings)` 返回完整可用的 `RAGChain` 实例
- 导入 `src.core.settings` 模块不触发网络请求

---

## 验收标准

### 功能验收
- [ ] `Settings` 类包含所有 outline 中列出的配置项
- [ ] API Key 字段设置 `repr=False`
- [ ] 必填字段缺失时 `Settings()` 抛出 `ValidationError`
- [ ] `RetrieverProtocol` 定义 `invoke(self, query: str) -> List[Document]`
- [ ] 5 个工厂函数全部实现
- [ ] `config.py` 删除所有对象实例化代码
- [ ] `rag_chain.py` 的 `retriever` 参数类型标注为 `RetrieverProtocol`
- [ ] `app.py` 使用 `create_rag_chain(settings)` 替代 `RAGChain.create()`
- [ ] `retrieval_eval.py` 使用 `RetrieverProtocol` 类型标注 + Settings 路径

### 质量验收
- [ ] `python src/run.py` 能正常启动
- [ ] 导入 `src.core.settings` 不触发网络请求
- [ ] MockRetriever 测试通过（Protocol 非侵入式抽象验证）

### 性能验收
- [ ] 工厂函数创建的对象使用缓存，不重复初始化

---

## 最佳实践自检清单

### 关键落地点（3 维）

- **SOLID 原则（依赖倒置）**：`RAGChain` 依赖 `RetrieverProtocol`（抽象）而非 `VectorRetriever`（具体）；`create_vectorstore` 返回 `VectorStore` 抽象类型；`create_llm` 返回 `BaseChatModel` 抽象类型
- **配置管理**：所有硬编码配置项迁移到 `Settings` 类，`Field(repr=False)` 防泄露，`@field_validator` 启动校验
- **设计模式（工厂方法）**：5 个工厂函数封装对象创建，消费方通过 `create_rag_chain(settings)` 一行获取完整链

### 常规落地

- [x] 模块分离：settings.py / factories.py / protocols.py 三文件各司其职
- [x] 架构分层：配置层（settings）→ 工厂层（factories）→ 业务层（RAGChain/Retriever）
- [x] 封装与抽象：`VectorRetriever` 内部实现不变，Protocol 非侵入式抽象
- [x] 设计模式：工厂方法模式（函数级，无过度设计）
- [x] 可观测性：工厂函数记录 info 日志（组件类型、配置参数）
- [x] 鲁棒性/容错：不支持的 provider/type 抛出 `NonRetryableError`；Settings 校验失败快速失败
- [x] 可测试性：Settings 可通过参数注入测试配置；RetrieverProtocol 可用 MockRetriever 替代
- [x] 可扩展性：`vectorstore_type` 和 `provider` 字段预留扩展点

### 豁免声明

- 无

---

## 前瞻性设计（精简）

### 与后续 Task 的接口衔接
- **Task 1.11**：`RAGChain` 的 `retriever: RetrieverProtocol` 类型标注为 Task 1.11 方法拆分提供类型安全基础
- **Task 2.2**：LangGraph 节点通过 `create_retriever(settings)` 获取检索器
- **Task 2.3**：LangGraph builder 通过 `create_llm()` + `create_retriever()` 组装依赖
- **Task 2.4**：`settings.checkpoint_db_path` 提供检查点数据库路径
- **Task 4.1**：Tavily 搜索工具使用 `settings.tavily_api_key`
- **Task 5.1**：FastAPI 启动时通过 `create_rag_chain(settings)` 创建链

---

## 参考技术文档（可后置）

- [pydantic_settings_guide.md](../../docs/task_1.10/pydantic_settings_guide.md) - Pydantic BaseSettings 深度指南
- [protocol_vs_abc.md](../../docs/task_1.10/protocol_vs_abc.md) - Protocol vs ABC 结构子类型对比
- [factory_pattern_guide.md](../../docs/task_1.10/factory_pattern_guide.md) - 工厂方法模式 + 惰性实例化
