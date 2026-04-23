"""generation 包 — Prompt 模板、RAG 链与引用提取的统一入口。"""

from .prompts import (
    FEW_SHOT_EXAMPLES,
    PROMPT_REGISTRY,
    SYSTEM_TEMPLATE_V1,
    SYSTEM_TEMPLATE_V2,
    HUMAN_TEMPLATE_V1,
    HUMAN_TEMPLATE_V2,
    PromptVersion,
    get_prompt,
)
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
from .exceptions import (
    CitationExtractionError,
    EmptyRetrievalError,
    GenerationError,
    LLMCallError,
)

__all__ = [
    # prompts
    "PromptVersion",
    "get_prompt",
    "PROMPT_REGISTRY",
    "FEW_SHOT_EXAMPLES",
    "SYSTEM_TEMPLATE_V1",
    "SYSTEM_TEMPLATE_V2",
    "HUMAN_TEMPLATE_V1",
    "HUMAN_TEMPLATE_V2",
    # rag_chain
    "RAGChain",
    "RAGResponse",
    "format_docs",
    # citation_chain
    "Citation",
    "CitationExtractor",
    "ValidatedCitation",
    # exceptions
    "CitationExtractionError",
    "EmptyRetrievalError",
    "GenerationError",
    "LLMCallError",
]
