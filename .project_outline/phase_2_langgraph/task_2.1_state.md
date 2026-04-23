## Task 2.1 LangGraph 状态定义

### 任务目标
定义 LangGraph 工作流的全局状态结构，作为所有节点间数据传递的唯一载体。

### 涉及文件
- `src/workflow/state.py`

### 面试级知识点
- **StateGraph 的三要素**：`StateGraph` 是 LangGraph 的核心构建块，通过节点、边和状态构造复杂工作流。状态在节点间传递，每个节点读取并返回更新后的状态。
- **TypedDict + Annotated 组合**：使用 `TypedDict` 定义状态字段类型，`Annotated` 配合 `add_messages` reducer 实现消息列表的增量追加而非覆盖。
- **StateGraph vs MessageGraph**：`MessageGraph` 是 `StateGraph` 的特化版本，状态仅包含 `messages` 字段；自定义 `StateGraph` 可扩展更多字段（如 `documents`、`iteration_count`）。

### 生产级注意事项
- **reducer 函数的选择**：对于 `messages` 字段必须使用 `add_messages`，确保每次节点返回的消息被追加而非覆盖；对于 `documents` 字段，根据业务需求选择覆盖或合并策略。
- **状态字段精简原则**：状态中只存储跨节点需要传递的数据，临时变量在节点内部处理。字段过多会增加序列化开销和检查点存储成本。
- **类型提示完整性**：所有字段必须有明确的类型注解，便于 IDE 提示和静态检查，减少运行时错误。

### 验收标准
- 定义 `GraphState` TypedDict，至少包含 `messages`（`Annotated[list, add_messages]`）、`documents`（`List[Document]`）、`iteration_count`（`int`）。
- 编写单元测试验证 `add_messages` reducer 的正确行为：连续两个节点返回消息列表，状态中的 `messages` 应包含两者合并结果。
- 状态定义文件可被 `nodes.py` 和 `builder.py` 正常导入，无循环依赖。