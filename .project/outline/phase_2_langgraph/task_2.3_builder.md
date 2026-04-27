## Task 2.3 条件边与图构建

### 任务目标
使用 `StateGraph` 构建完整的问答工作流，包含条件分支和循环逻辑。

### 涉及文件
- `src/workflow/builder.py`
- `src/workflow/edges.py`

### 面试级知识点
- `add_node` **+** `add_edge` **+** `add_conditional_edges`：LangGraph 的图构建三部曲——先添加所有节点，再连接边，条件边通过路由函数决定下一跳。
- **START 和 END 常量**：`START` 表示图的入口节点，`END` 表示终止；必须显式连接，否则图无法编译。
- **循环与递归限制**：通过 `RunnableConfig` 中的 `recursion_limit` 控制最大迭代次数（默认 25），防止死循环。
- **CompiledGraph**：`compile()` 将 `StateGraph` 转换为可执行的 `CompiledGraph`，支持 `invoke`、`stream`、`astream` 等运行方式。

### 生产级注意事项
- **条件边的路由函数必须幂等**：给定相同状态，路由函数应返回相同的标签，否则会导致不可预测的执行路径。
- **添加"安全阀"节点**：当 `iteration_count` 超过阈值时，强制跳转到 `END` 或返回预设回复，防止无限循环耗尽资源。
- **图编译检查**：`compile()` 会验证节点连接完整性和循环检测，编译失败时错误信息应友好提示缺失的边。
- **图的模块化组织**：将图构建逻辑封装在 `build_graph()` 函数中，返回 `CompiledGraph`，便于测试和不同环境配置。

### 验收标准
- 图包含以下节点：`route` → `retrieve` → `generate`，以及一个 `fallback` 节点处理无法回答的情况。
- 条件边逻辑：`route` 根据意图分类跳转到 `retrieve` 或 `fallback`；`generate` 后跳转到 `END`。
- 运行 `builder.build_graph()` 能成功编译，无节点未连接或循环检测错误。
- 使用 `graph.get_graph().draw_mermaid_png()` 生成流程图，视觉验证图结构正确。