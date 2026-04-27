"""generation 包 — RAG Chain 生成层核心 API。

核心职责：
    - RAGChain: 问答链编排（检索 → 生成 → 引用提取）
    - Prompt 管理: 版本化 Prompt 模板
    - Citation: 引用提取与验证
    - Exceptions: 生成模块异常体系

内部实现细节（不导出）：
    - SYSTEM_TEMPLATE_V1/V2: Prompt 模板字符串（内部使用）
    - HUMAN_TEMPLATE_V1/V2: Prompt 模板字符串（内部使用）
    - FEW_SHOT_EXAMPLES: Few-shot 示例（内部使用）
    - PROMPT_REGISTRY: Prompt 注册表（内部使用）
    - CitationItem/CitationList: Pydantic Schema（内部使用）
    - CITATION_EXTRACTION_PROMPT: Prompt 模板（内部使用）

使用示例：
    from src.generation import RAGChain, RAGResponse, get_prompt, PromptVersion

    prompt = get_prompt(PromptVersion.V2, include_few_shot=True)
    chain = RAGChain(retriever=..., llm=..., prompt=prompt)
    result = chain.invoke("LangGraph 是什么？")
"""

from .rag_chain import (
    RAGChain,
    RAGResponse,
    format_docs,
)
from .citation_chain import (
    Citation,
    CitationExtractor,
    ValidatedCitation,
)
from .prompts import (
    PromptVersion,
    get_prompt,
)
from .exceptions import (
    CitationExtractionError,
    EmptyRetrievalError,
    GenerationError,
    LLMCallError,
)

__all__ = [
    # rag_chain
    "RAGChain",
    "RAGResponse",
    "format_docs",
    # citation_chain
    "Citation",
    "CitationExtractor",
    "ValidatedCitation",
    # prompts（只导出工厂函数和枚举，不导出模板字符串）
    "PromptVersion",
    "get_prompt",
    # exceptions
    "CitationExtractionError",
    "EmptyRetrievalError",
    "GenerationError",
    "LLMCallError",
]
