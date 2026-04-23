## Task 5.5 生产级配置管理与安全加固

### 任务目标
完善配置管理系统,支持多环境(开发、测试、生产)配置切换,并实施 API 安全措施(限流、CORS、认证)以应对生产部署需求。

### 涉及文件
- `src/core/config.py`
- `api/middleware.py`
- `.env.example`

### 面试级知识点
- **Pydantic Settings 管理**:使用 `pydantic_settings.BaseSettings` 从环境变量和 `.env` 文件自动加载配置,提供类型验证和默认值。
- **多环境配置策略**:通过 `ENVIRONMENT` 环境变量(`development`/`staging`/`production`)加载不同配置类,例如生产环境强制要求某些变量非空。
- **API 限流算法**:固定窗口、滑动窗口、令牌桶。FastAPI 生态常用 `slowapi`(基于 `limits` 库)实现限流,防止恶意请求耗尽 LLM 配额。
- **CORS 配置**:跨域资源共享是浏览器安全策略。FastAPI 使用 `CORSMiddleware` 配置允许的来源、方法、头部。生产环境应将 `allow_origins` 设为具体域名,而非 `*`。

### 生产级注意事项
- **敏感信息管理**:API Key、数据库密码等敏感配置绝不写入代码或镜像,必须通过环境变量或 Secret 管理工具(如 Docker Secrets、Kubernetes Secrets)注入。
- **限流策略设计**:针对 `/chat` 端点实施基于 IP 或 API Key 的限流,例如每分钟 10 次请求,超出返回 429。需区分流式和非流式请求的计数方式。
- **认证机制**:若需对外开放服务,建议实现简单的 API Key 认证(请求头 `X-API-Key`)或 JWT 认证。FastAPI 的依赖注入可优雅实现。
- **日志脱敏**:确保 API Key 等敏感信息不会出现在日志或错误响应中。Pydantic 模型可使用 `SecretStr` 类型自动隐藏。
- **安全响应头**:添加 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY` 等安全头,降低点击劫持和 MIME 嗅探风险。

### 验收标准
- `config.py` 使用 `BaseSettings` 定义 `Settings` 类,所有配置项可从环境变量读取,并附带默认值和描述。
- 提供 `.env.example` 文件,列出所有必需和可选的环境变量,供用户复制使用。
- API 服务启用限流中间件:对 `/api/v1/chat` 限制 10 req/min,超过后返回 429 并附带 `Retry-After` 头。
- CORS 配置仅允许 `http://localhost:7860`(Gradio UI)和 `http://localhost:3000`(假设的前端)。
- 敏感配置(如 `OPENAI_API_KEY`)在日志中被自动脱敏(显示为 `***`)。
