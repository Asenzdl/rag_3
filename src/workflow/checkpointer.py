"""检查点持久化模块 — 为 LangGraph 工作流提供状态持久化能力。

本模块封装 SqliteSaver 的创建和初始化逻辑，通过上下文管理器模式
管理数据库连接生命周期。

核心设计：
1. **上下文管理器模式**：包装 SqliteSaver.from_conn_string，
   确保连接在退出时正确关闭
2. **依赖倒置**：返回 BaseCheckpointSaver 抽象类型，
   预留 PostgresSaver 扩展接口
3. **防御性初始化**：自动创建数据库目录 + 调用 setup()

为什么独立为模块而非放在 builder.py 中（设计决策）：
    1. 职责单一：checkpointer.py 负责"创建和初始化检查点"，
       builder.py 负责"组装图"
    2. 生命周期隔离：checkpointer 是资源（数据库连接），
       其生命周期由调用方管理，不应与图的构建逻辑耦合
    3. 可替换性：未来切换 PostgresSaver 只需修改此模块

面试知识点：
    - Checkpointer 的作用：每次节点执行后自动保存状态快照，
      支持流程暂停/恢复、时间旅行调试、多会话隔离
    - MemorySaver vs SqliteSaver vs PostgresSaver：
      MemorySaver 仅内存存储，进程重启即丢失；
      SqliteSaver 本地文件持久化，适合单机生产；
      PostgresSaver 支持分布式部署
    - thread_id 的作用：通过 config["configurable"]["thread_id"]
      区分不同会话，同一 thread_id 的所有调用共享状态历史
"""

import os
from contextlib import contextmanager
from typing import Iterator

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver

from src.core.settings import Settings

logger = structlog.get_logger(__name__)


# ============================================================
# 检查点管理器工厂函数
# ============================================================

@contextmanager
def create_checkpointer(settings: Settings) -> Iterator[BaseCheckpointSaver]:
    """创建检查点管理器（上下文管理器模式）。

    为什么用上下文管理器而非普通工厂函数（设计决策）：
        SqliteSaver.from_conn_string 是 @contextmanager，
        在退出时自动关闭 sqlite3 连接。本函数包装它，
        确保调用方无需关心连接清理细节。
        如果绕过 from_conn_string 直接创建 SqliteSaver(conn)，
        调用方必须自行管理连接关闭——这是资源泄漏的常见来源。

    为什么返回 BaseCheckpointSaver 而非 SqliteSaver（DIP）：
        依赖倒置——调用方依赖抽象类型而非具体实现。
        未来切换 PostgresSaver 时，只需修改此函数，
        调用方代码无需变更。

    为什么在内部调用 setup() 而非让调用方调用（封装）：
        setup() 是数据库初始化细节（创建表），属于检查点创建的
        原子操作。setup() 是幂等的（重复调用安全），在内部调用
        不会产生副作用。若留给调用方，遗忘调用会导致运行时异常
        （表不存在），且错误信息不直观。

    为什么自动创建目录而非依赖部署约定（鲁棒性）：
        sqlite3.connect 不会创建父目录，目录不存在时抛出
        FileNotFoundError。自动创建是防御性编程，避免因
        部署环境差异（如全新机器上首次运行）导致启动失败。

    Args:
        settings: 全局配置实例，读取 checkpoint_db_path

    Yields:
        配置好的检查点管理器实例（BaseCheckpointSaver 子类）

    Example:
        with create_checkpointer(settings) as checkpointer:
            graph = build_graph(settings, checkpointer=checkpointer)
            result = graph.invoke(
                {"messages": [HumanMessage(content="你好")]},
                config={"configurable": {"thread_id": "session-1"}},
            )
    """
    # 第1步：提取数据库路径
    db_path = settings.checkpoint_db_path

    # 第2步：确保数据库目录存在
    #   为什么：sqlite3.connect 不会自动创建父目录
    #   边界：os.path.dirname(":memory:") 返回 "" → makedirs("") 抛异常
    #   处理：仅当 dirname 非空时调用 makedirs（":memory:" 和相对路径文件名跳过）
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    logger.info("检查点管理器创建中", db_path=db_path)

    # 第3步：调用 SqliteSaver.from_conn_string 创建检查点管理器
    #   from_conn_string 是 @contextmanager，退出时自动关闭 sqlite3 连接
    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        # 第4步：调用 setup() 初始化数据库表
        #   为什么首次必须调用：创建 checkpoints 等必要表
        #   为什么重复调用安全：setup() 内部检查表是否存在（幂等）
        checkpointer.setup()

        logger.info("检查点管理器初始化完成", db_path=db_path)

        # 第5步：yield 检查点管理器
        #   with 块退出时，from_conn_string 自动关闭 sqlite3 连接
        yield checkpointer


__all__ = [
    "create_checkpointer",
]
