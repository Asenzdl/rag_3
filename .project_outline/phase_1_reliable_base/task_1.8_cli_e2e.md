## Task 1.8 CLI 交互入口与端到端测试

### 任务目标
构建命令行交互界面，支持多轮问答，并完成一轮完整的端到端功能验证。

### 涉及文件
- `src/app.py`
- `tests/test_e2e.py`

### 面试级知识点
- **REPL 设计模式**：Read-Eval-Print Loop 在 Python 中的简单实现（`while True: input()`）。
- **会话状态管理**：如何在 CLI 中维护对话历史（最简单的实现：内存中的 `List[BaseMessage]`）。
- **端到端测试的边界**：E2E 测试应模拟真实用户输入，但不依赖外部网络（使用 Mock 或本地向量库）。

### 生产级注意事项
- **优雅退出**：捕获 `KeyboardInterrupt` 和 `EOFError`，打印告别信息后退出。
- **环境变量加载**：启动时使用 `dotenv.load_dotenv()` 确保 API Key 正确加载。
- **E2E 测试独立性**：测试用例使用固定的评估数据集，不依赖特定 API 响应内容（仅验证是否返回非空字符串和引用格式）。

### 验收标准
- 启动 `app.py`，连续进行 5 轮问答（包含一个与文档无关的问题），程序不崩溃。
- 输入 `exit` 或 `quit` 能正常退出。
- 运行 `pytest tests/test_e2e.py` 通过全部 5 个测试用例（对应 Task 1.2 数据集中的 5 个问题）。
