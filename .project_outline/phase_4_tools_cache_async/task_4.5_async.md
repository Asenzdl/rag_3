## Task 4.5 异步处理与吞吐量优化

### 任务目标
将 LangGraph 工作流和检索模块全面异步化,支持 FastAPI 异步端点的高并发请求处理,并通过并发检索和批量处理提升系统吞吐量。

### 涉及文件
- `src/workflow/builder.py`(异步图运行)
- `src/retrieval/*.py`(异步检索方法)
- `src/utils/async_helpers.py`

### 面试级知识点
- **Python 异步编程的核心**:`async/await` 语法、事件循环(Event Loop)、协程(Coroutine)。理解 `asyncio.gather` 并发执行多个 IO 密集型任务(如 LLM API 调用、向量检索、网络搜索)以降低总延迟。
- **LangGraph 的异步支持**:`CompiledGraph` 提供 `ainvoke`、`astream` 方法,内部节点函数可以是异步的。LangGraph 会自动处理异步节点的执行顺序。
- **检索的并发优化**:MultiQuery 检索时,多个查询变体应并发执行检索,而非串行。Phase 3.1 已提及,此处正式实现。
- **异步与同步的边界**:FastAPI 路由是异步的,但 LangChain 的某些组件(如 Chroma 的相似度搜索)同步方法居多。需使用 `asyncio.to_thread` 将同步调用放到线程池中执行,避免阻塞事件循环。

### 生产级注意事项
- **将关键节点改造为异步**:`retrieve` 节点、`web_search` 节点、`generate` 节点(LLM 调用)均改为 `async def`。LangGraph 节点函数签名支持同步和异步混合,但推荐统一为异步以减少心智负担。
- **同步组件的线程池处理**:Chroma 的 `similarity_search` 是同步方法,在异步节点中使用:
  ```python
  docs = await asyncio.to_thread(vectorstore.similarity_search, query, k=top_k)
  ```
- **连接池管理**:异步 HTTP 客户端(如 `httpx.AsyncClient`)应使用连接池,避免每次请求都新建连接。在应用启动时创建全局 `AsyncClient` 并复用。
- **并发请求的压力测试**:使用 `locust` 或 `wrk` 对 FastAPI 端点进行压力测试,记录 QPS、P95 延迟、错误率,验证异步化后的吞吐量提升。
- **限流与背压**:高并发时,LLM API 有速率限制。需实现令牌桶或漏桶限流器(如 `asyncio-throttle`),在应用层排队请求,避免触发 API 429 错误。

### 验收标准
- 所有检索器类(`BaseRetriever`、`MultiQueryRetriever` 等)新增异步方法 `aretrieve(query: str) -> List[Document]`。
- LangGraph 节点函数 `retrieve_node`、`generate_node`、`web_search_node` 改为 `async def`。
- 运行并发测试脚本:同时发起 10 个相同问题请求,使用 `asyncio.gather` 并发执行,总耗时接近单次请求耗时(而非 10 倍)。
- 对比同步版本和异步版本的吞吐量:使用 `time` 命令或 `pytest-benchmark` 记录,异步版本吞吐量至少提升 50%(在 IO 密集场景下)。
- FastAPI 端点(Phase 5 前置)能正确调用异步图运行方法 `await graph.ainvoke(...)`,且不阻塞其他请求。
