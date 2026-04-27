"""RAG 系统主入口 — 只导出核心生产 API。

核心 API（FastAPI/其他服务会调用的）：
    - RAGChain: 问答核心（invoke/stream/ainvoke）
    - RAGResponse: 响应数据结构
    - settings: 全局配置单例
    - Settings: 配置类定义

内部工具（不从主入口导出，需显式导入）：
    - src.ingestion.*: 数据预处理（离线管道）
    - src.evaluation.*: 模型评估（测试验证）
    - src.app.*: CLI 交互界面（用户界面层）
    - src.utils.*: 基础设施（重试/日志）
    - src.core.*: 工厂函数/异常体系（被 RAGChain 内部使用）

使用示例：
    from src import RAGChain, RAGResponse, settings
    from src.core import create_rag_chain

    chain = create_rag_chain(settings)
    result = chain.invoke("LangGraph 是什么？")
    print(result.answer)
"""

from src.core.config import settings
from src.core.settings import Settings
from src.generation.rag_chain import RAGChain, RAGResponse

__all__ = [
    # 核心生产 API
    "RAGChain",
    "RAGResponse",
    "settings",
    "Settings",
]