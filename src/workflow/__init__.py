"""workflow 包 — LangGraph 工作流定义。

本包定义 LangGraph 的状态结构、节点函数、图构建逻辑。

公共 API：
    - GraphState：工作流全局状态（TypedDict），所有节点间数据传递的唯一载体

内部模块（不从主入口导出，需显式导入）：
    - workflow.state：状态字段定义
    - workflow.nodes（Task 2.2）：节点函数
    - workflow.builder（Task 2.3）：图构建
    - workflow.edges（Task 2.3）：条件边与路由
    - workflow.checkpointer（Task 2.4）：检查点持久化
"""

from src.workflow.state import GraphState

__all__ = [
    "GraphState",
]
