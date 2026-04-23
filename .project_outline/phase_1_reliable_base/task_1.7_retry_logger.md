## Task 1.7 LLM 调用重试与结构化日志

### 任务目标
为 LLM 调用添加自动重试机制（应对 Rate Limit），并集成结构化日志，使系统行为可追溯。

### 涉及文件
- `src/utils/retry.py`
- `src/utils/logger.py`
- `src/core/exceptions.py`

### 面试级知识点
- **指数退避 (Exponential Backoff)** 原理：为何能有效避免雪崩效应。
- **幂等性**：LLM 生成任务天然非幂等，重试策略需区分可重试错误（429、5xx）和不可重试错误（401、400）。
- **结构化日志的价值**：JSON 格式日志便于导入 ELK/Loki 等工具分析，而非 `print` 调试。

### 生产级注意事项
- **使用 tenacity 库**：装饰器方式管理重试逻辑，简洁可靠。
  ```python
  @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
  ```
- **日志上下文绑定**：使用 `structlog` 的 `bind()` 方法为每条日志附加 `request_id`、`user_id`、`session_id`，便于追踪单次请求全链路。
- **敏感信息脱敏**：日志中不应包含完整 API Key 或用户个人数据。

### 验收标准
- 模拟 API 返回 429 错误（可通过 Mock 或临时修改请求头），观察日志确认发生了 3 次重试。
- 日志输出为 JSON 格式，包含 `timestamp`、`level`、`event`、`request_id` 字段。
- 在正常问答过程中，日志中记录了检索耗时、LLM 调用耗时、Token 使用量（如果 API 返回）。
