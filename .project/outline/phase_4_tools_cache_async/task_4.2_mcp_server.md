## Task 4.2 MCP 服务端

### 任务目标
使用 FastMCP 将本地检索能力封装为 MCP(Model Context Protocol)服务,允许外部 AI 应用(如 Claude Desktop、Cursor)通过标准协议调用你的知识库检索功能。此任务为**加分项**,在面试中可展示你对前沿协议的理解和扩展能力。

### 涉及文件
- `src/tools/mcp_server.py`
- `mcp_config.json`(MCP 客户端配置示例)

### 面试级知识点
- **MCP 协议的核心定位**:MCP 是 Anthropic 提出的开放协议,旨在标准化 AI 应用与外部数据源/工具的连接方式。它解决了"每个 AI 应用都要单独开发插件"的碎片化问题,相当于 AI 领域的"USB-C 接口"。
- **MCP 的三层架构**:Host(AI 应用,如 Claude Desktop)→ Client(协议客户端,嵌入在 Host 中)→ Server(你实现的 MCP 服务,暴露工具/资源)。
- **FastMCP 的作用**:Python 库,简化 MCP Server 的开发,提供装饰器方式定义 `@mcp.tool()` 和 `@mcp.resource()`。
- **MCP 与本项目的结合点**:你的 RAG 系统的检索能力可通过 MCP Server 暴露,任何支持 MCP 的 AI 应用都能直接检索你的本地知识库,无需重复开发检索逻辑。

### 生产级注意事项
- **明确此任务的优先级**:Phase 4 的核心是缓存和异步,MCP 属于"扩展能力展示",不作为 Phase 4 的强制验收项。可在完成 4.1、4.3、4.4 后再选择性实现,或标记为 `[Optional]`。
- **MCP Server 的部署模式**:本地开发时使用 `stdio` 传输(标准输入输出),生产环境可切换为 HTTP + SSE 传输。
- **工具定义的精细化**:暴露的检索工具应支持参数 `query`、`top_k`、`filter_category`,并返回标准化的文档列表(含 title、snippet、url)。
- **安全考量**:MCP Server 运行在本地时具有访问本地文件系统的能力,需确保不暴露敏感路径。工具函数中应限制可访问的资源范围。
- **面试中的话术**:"我实现了一个 MCP Server,将 RAG 检索能力标准化,这样团队其他成员在 Claude Desktop 中就能直接查询内部文档,无需为每个工具单独开发插件。这体现了我在架构扩展性和生态兼容性上的思考。"

### 验收标准(若选择实现)
- 使用 FastMCP 创建 `LangChainDocsMCPServer`,至少暴露一个工具 `search_langchain_docs`。
- 启动 MCP Server:`python src/tools/mcp_server.py`(stdio 模式)。
- 编写 `mcp_config.json` 示例文件,供 Claude Desktop 等客户端配置使用。
- 在 Claude Desktop 中成功连接 MCP Server,通过自然语言提问触发检索工具调用,验证返回结果的正确性。
- 文档化 MCP 集成步骤(`docs/mcp_integration.md`)。
