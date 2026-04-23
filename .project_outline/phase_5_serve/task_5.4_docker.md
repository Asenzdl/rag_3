## Task 5.4 Docker 容器化与 Docker Compose 编排

### 任务目标
将整个 RAG 系统(FastAPI 服务 + 可选的 UI + Chroma 向量库 + SQLite 缓存)打包为 Docker 镜像,并通过 Docker Compose 实现一键启动,确保环境一致性。

### 涉及文件
- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `docker/entrypoint.sh`

### 面试级知识点
- **Docker 镜像分层构建原理**:利用 Docker 的层缓存机制优化构建速度——先复制依赖文件(`pyproject.toml`)并安装依赖,再复制源代码。这样源代码变更时无需重新安装依赖。
- **多阶段构建(Multi-stage Build)**:第一阶段安装构建依赖并编译(如有需要),第二阶段仅复制运行时必需文件,显著减小最终镜像体积。
- **Docker Compose 的服务编排**:定义多个服务(`api`、`ui`、`chroma` 可选),通过内部网络通信,通过卷(volumes)持久化数据。
- **环境变量与配置管理**:敏感信息(API Key)通过 `.env` 文件注入,不写入镜像;非敏感配置可通过环境变量覆盖默认值。

### 生产级注意事项
- **基础镜像选择**:推荐 `python:3.11-slim-bookworm`,兼顾体积小和兼容性。避免使用 `alpine`,因为某些 Python 包(如 `grpcio`)在 musl libc 上编译困难。
- **非 root 用户运行**:在 Dockerfile 中创建 `appuser` 并切换,遵循最小权限原则,防止容器逃逸风险。
- **健康检查指令**:在 Dockerfile 中添加 `HEALTHCHECK --interval=30s --timeout=10s CMD curl -f http://localhost:8000/health || exit 1`,使 Docker 能自动检测服务状态。
- **数据持久化**:向量库数据(`data/chroma/`)和缓存数据库(`db/`)应通过 Docker volumes 挂载,防止容器重启后数据丢失。
- **日志收集**:配置 Docker 的 logging driver 为 `json-file` 或 `syslog`,并限制日志文件大小,防止磁盘被日志占满。

### 验收标准
- 编写 `Dockerfile` 并构建镜像:`docker build -t langgraph-rag:latest .`,镜像体积 < 2GB。
- 编写 `docker-compose.yml`,包含 `api` 服务和 `ui` 服务(可选),通过 `depends_on` 控制启动顺序。
- 运行 `docker compose up -d`,访问 `http://localhost:8000/docs` 确认 API 可用,访问 `http://localhost:7860` 确认 UI 可用。
- 在 `.env` 文件中配置 `OPENAI_API_KEY` 等变量,`docker compose` 能正确读取并注入容器。
- 停止容器 `docker compose down` 后,向量库数据因卷挂载得以保留;再次启动 `docker compose up`,之前导入的文档仍存在。
- 编写 `docker/entrypoint.sh` 脚本,在容器启动时自动执行数据库迁移或索引检查(如需要)。
