## Task 5.1 FastAPI 服务封装与 RESTful API 设计

### 任务目标
使用 FastAPI 将 LangGraph 工作流封装为 HTTP 服务,提供标准的 `/chat` 端点(支持流式和非流式响应)、健康检查端点、以及 API 文档自动生成。

### 涉及文件
- `api/main.py`
- `api/routers/chat.py`
- `api/dependencies.py`
- `api/schemas.py`

### 面试级知识点
- **FastAPI 的核心优势**:异步原生支持、自动 OpenAPI 文档生成、Pydantic v2 数据验证、依赖注入系统。这些特性使其成为 Python 异步 Web 服务的首选框架。
- **RESTful API 设计最佳实践**:资源命名规范(`/chat` 而非 `/ask`)、HTTP 方法语义(POST 用于创建新对话)、状态码含义(200 成功、400 请求错误、500 服务器错误)。
- **流式响应 vs 非流式响应**:流式响应(Server-Sent Events 或 NDJSON)能显著提升用户体验,用户可在 LLM 生成 token 时实时看到内容,而非等待完整答案。面试中要能说清 SSE 协议与 WebSocket 的区别及适用场景。
- **依赖注入在 FastAPI 中的应用**:通过 `Depends` 注入共享资源(如配置对象、向量库连接、Graph 实例),实现代码解耦和测试友好。

### 生产级注意事项
- **请求/响应模型的 Pydantic 定义**:
  ```python
  class ChatRequest(BaseModel):
      question: str
      thread_id: Optional[str] = None  # 用于恢复会话
      stream: bool = False
  
  class ChatResponse(BaseModel):
      answer: str
      sources: List[SourceCitation]
      thread_id: str
  ```
- **全局 Graph 实例管理**:在应用启动时(`@app.on_event("startup")`)初始化向量库、LLM、Graph,作为单例复用,避免每次请求都重新加载模型。
- **并发请求的线程安全**:LangGraph 的 `CompiledGraph` 实例是线程安全的(内部状态通过 `config` 中的 `thread_id` 隔离)。但 Chroma 客户端和 SQLite 缓存的并发访问需注意:使用连接池或锁机制。
- **请求超时与取消处理**:FastAPI 支持 `Request` 对象的 `is_disconnected()` 方法检测客户端断开。对于长时间运行的 LLM 生成,应定期检查此状态并提前终止以节省资源。
- **API 版本控制**:通过 URL 路径前缀(如 `/api/v1/chat`)实现版本控制,为未来 API 变更留出空间。

### 验收标准
- 启动 FastAPI 服务:`uvicorn api.main:app --reload`,访问 `http://localhost:8000/docs` 能看到自动生成的 Swagger UI。
- 使用 `curl` 或 Postman 发送 POST 请求到 `/api/v1/chat`,请求体 `{"question": "What is LangChain?", "stream": false}`,返回 200 状态码和 JSON 格式答案(含来源)。
- 发送流式请求 `{"stream": true}`,响应头 `Content-Type: text/event-stream`,客户端能逐 token 接收数据。
- 健康检查端点 `GET /health` 返回 `{"status": "ok", "vector_store": "connected"}`。
- 不同 `thread_id` 的请求相互隔离,对话历史正确保留。
