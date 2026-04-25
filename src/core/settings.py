"""12-Factor App 配置管理 — Pydantic BaseSettings 实现。

本模块将所有硬编码配置项集中到 Settings 类中，实现：
1. 类型安全：API Key 必须是 str，端口必须是 int，启动时自动校验
2. 防泄露：Field(repr=False) 防止日志/调试时打印明文 Key
3. IDE 补全：settings.deepseek_api_key 比 os.getenv("DEEPSEEK_API_KEY") 更友好
4. 启动时快速失败：必填字段缺失时 ValidationError 立即报错
5. 12-Factor App：环境变量 > .env 文件 > 默认值，同一份构建物走不同环境

优先级机制：
    环境变量 > .env 文件 > Field 默认值
    这是 Pydantic BaseSettings 的核心特性，确保：
    - 本地开发：.env 文件提供默认配置
    - 生产部署：环境变量覆盖 .env（同一份构建物走不同环境）
"""

from typing import ClassVar

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """RAG 系统全局配置 — 集中管理所有配置项。

    配置分组：
        - API Keys（repr=False 防泄露）
        - Base URLs
        - 向量库配置
        - Embedding 配置
        - 评估路径
        - 检查点路径（Phase 2 预留）

    使用方式：
        from src.core.config import settings
        api_key = settings.deepseek_api_key
        persist_dir = settings.chroma_persist_directory
    """

    # ===== API Keys（repr=False 防止日志泄露）=====
    deepseek_api_key: str = Field(repr=False, description="DeepSeek API Key")
    qwen_api_key: str = Field(repr=False, description="Qwen API Key")
    tavily_api_key: str = Field(
        default="", repr=False, description="Tavily 搜索 API Key（Phase 4）"
    )

    # ===== Base URLs =====
    deepseek_base_url: str = Field(description="DeepSeek API Base URL")
    qwen_base_url: str = Field(description="Qwen API Base URL")
    ollama_base_url: str = Field(
        default="http://localhost:11434", description="Ollama 服务地址"
    )

    # ===== 向量库配置 =====
    vectorstore_type: str = Field(
        default="chroma", description="向量库类型（chroma/faiss/pinecone）"
    )
    chroma_persist_directory: str = Field(
        default="db/langchain_docs_db1", description="Chroma 数据目录"
    )
    chroma_collection_name: str = Field(
        default="langchain_docs1", description="Chroma 集合名称"
    )

    # ===== Embedding 配置 =====
    embedding_model: str = Field(
        default="qwen3-embedding:4b", description="Ollama Embedding 模型名"
    )

    # ===== 评估路径 =====
    eval_qa_path: str = Field(
        default="data/eval/qa_pairs.json", description="评估 QA 对路径"
    )
    eval_report_path: str = Field(
        default="data/eval/baseline_retrieval_report.md",
        description="评估报告输出路径",
    )

    # ===== 检查点路径（Phase 2 预留）=====
    checkpoint_db_path: str = Field(
        default="db/checkpoints.db", description="LangGraph 检查点数据库路径"
    )

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("deepseek_api_key", "qwen_api_key")
    @classmethod
    def _validate_api_key_not_blank(cls, v: str) -> str:
        """校验 API Key 非空非空白。

        为什么需要此校验：
            .env 中可能设为空字符串（DEEPSEEK_API_KEY=""），
            Pydantic 的 str 类型会将空字符串视为合法值。
            去除首尾空白后若为空，应抛出 ValidationError 快速失败。
        """
        if not v.strip():
            raise ValueError("API Key 不能为空或纯空白")
        return v
