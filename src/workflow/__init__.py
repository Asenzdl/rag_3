"""workflow 包 — LangGraph 工作流定义。

本包定义 LangGraph 的状态结构、节点函数、图构建逻辑、检查点持久化。

公共 API：
    - GraphState：工作流全局状态（TypedDict），所有节点间数据传递的唯一载体
    - create_workflow_nodes：工厂函数，创建路由/检索/生成节点（闭包注入依赖）
    - build_graph：图构建函数，组装并编译完整问答工作流
    - create_checkpointer：检查点管理器工厂（上下文管理器模式）

内部模块（不从主入口导出，需显式导入）：
    - workflow.state：状态字段定义
    - workflow.routing：路由逻辑与意图分类
    - workflow.nodes：节点函数 + 工厂函数
    - workflow.edges：条件边路由函数
    - workflow.builder：图构建 + 简单终端节点
    - workflow.checkpointer：检查点持久化
"""

from .builder import build_graph
from .checkpointer import create_checkpointer
from .nodes import create_workflow_nodes
from .state import GraphState

__all__ = [
    "GraphState",
    "build_graph",
    "create_checkpointer",
    "create_workflow_nodes",
]
