## Task 5.3 Web UI 构建(Gradio 或 Streamlit)

### 任务目标
使用 Gradio 或 Streamlit 快速构建一个 Web 交互界面,提供对话输入框、流式回答展示、来源引用折叠显示、会话历史管理等功能,降低非技术用户的体验门槛。

### 涉及文件
- `ui/app.py`
- `ui/components.py`

### 面试级知识点
- **Gradio vs Streamlit 的选型**:Gradio 专为 ML 模型演示设计,原生支持聊天界面、流式输出、状态管理;Streamlit 更通用,但聊天场景需手动管理状态。本项目推荐 Gradio 的 `ChatInterface`。
- **Gradio 的** `gr.ChatInterface` **高级用法**:只需提供一个 `fn` 函数(接收 `message, history`,返回生成器),Gradio 自动处理 UI 渲染、流式输出、历史记录。
- **前后端分离 vs 一体化**:Gradio 应用可直接调用 Python 后端逻辑(同进程),开发效率极高;生产环境可通过 API 模式(`gr.Interface` 的 `api_mode`)暴露给自定义前端。

### 生产级注意事项
- **Gradio 应用的部署模式**:开发时使用 `demo.launch(share=False)`;生产环境建议配合 Nginx 反向代理,或使用 Hugging Face Spaces 托管。
- **会话管理**:Gradio 默认每个浏览器 tab 有独立的会话 ID(`gr.Request` 中的 `session_hash`),可用于区分不同用户的对话历史。需将此 `session_hash` 映射到 LangGraph 的 `thread_id`。
- **自定义样式与品牌化**:Gradio 支持自定义 CSS 和主题,可调整配色、字体以符合个人或公司品牌。
- **错误提示的用户友好性**:捕获业务异常(如知识库未就绪、API Key 无效),在 UI 中显示友好的错误消息,而非 Python traceback。

### 验收标准
- 运行 `python ui/app.py`,浏览器自动打开本地 Gradio 界面。
- 在输入框输入问题,回答以打字机效果流式展示,引用来源以折叠卡片形式显示在回答下方。
- 界面支持多轮对话,用户可基于上文进行追问,系统能正确理解上下文。
- 提供"清除对话"按钮,点击后重置当前会话的对话历史。
- Gradio 应用能通过环境变量配置后端 API 地址(若前后端分离),或直接调用本地 Graph 实例(同进程)。
