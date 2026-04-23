## Task 5.2 流式响应的 SSE 实现

### 任务目标
在 FastAPI 中实现符合 Server-Sent Events(SSE)规范的流式响应,将 LangGraph 的 `astream_events` 输出的 token 级数据实时推送给客户端。

### 涉及文件
- `api/routers/chat.py`
- `api/streaming.py`

### 面试级知识点
- **SSE 协议规范**:基于 HTTP,响应头 `Content-Type: text/event-stream`,数据格式为 `data: <message>\n\n`。与 WebSocket 相比,SSE 是单向推送(服务器→客户端)、自动重连、更轻量。
- **LangGraph 的** `astream_events` **API**:`astream_events` 提供节点级和 token 级的事件流,可精细控制流式输出内容。例如,只推送 `on_chat_model_stream` 事件的 token,忽略其他节点事件。
- **流式响应的错误处理**:当生成过程中发生错误时,SSE 流应能优雅终止,并向客户端发送错误事件(如 `event: error\ndata: {"message": "LLM timeout"}\n\n`)。
- **背压处理**:当客户端接收速度慢于服务器生成速度时,FastAPI 的 `StreamingResponse` 会自动处理 TCP 背压,无需额外代码。

### 生产级注意事项
- **使用** `fastapi.responses.StreamingResponse`:
  ```python
  async def event_generator():
      async for event in graph.astream_events(...):
          if event["event"] == "on_chat_model_stream":
              token = event["data"]["chunk"].content
              yield f"data: {json.dumps({'token': token})}\n\n"
      yield "data: [DONE]\n\n"
  return StreamingResponse(event_generator(), media_type="text/event-stream")
  ```
- **合理设置** `heartbeat`:长时间无 token 输出时(如 LLM 正在思考),发送注释行 `: heartbeat\n\n` 保持连接活跃,防止代理服务器超时断开。
- **前端兼容性**:标准 SSE 使用浏览器内置的 `EventSource` API,但它不支持自定义请求头(如 Authorization)。生产环境建议改用 Fetch API + 手动解析流,或将 token 放在 URL 参数中。
- **流式响应的可观测性**:记录流式传输的开始时间、首个 token 时间(TTFT)、结束时间,作为性能指标输出到日志。

### 验收标准
- 使用 `curl -N` 测试流式端点,能实时看到 token 逐字输出,最后以 `[DONE]` 结束。
- 前端测试页面(可用简单的 HTML + JavaScript)能连接 SSE 端点并动态渲染回答内容。
- 流式传输过程中模拟 LLM 调用失败(如 API Key 错误),客户端能接收到错误事件并停止渲染。
- 在日志中记录每次流式请求的 TTFT(首个 token 延迟)。
