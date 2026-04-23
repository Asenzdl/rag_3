"""引用提取与验证模块。

本模块负责从 LLM 生成的回答文本中提取引用信息并验证其真实性，
支持正则解析（默认）和结构化输出（可选）两种策略。

核心设计：
1. **策略模式**：CitationExtractor 根据配置选择正则或结构化输出策略，
   两种策略产出统一的 List[ValidatedCitation]，调用方无需关心内部实现。

2. **验证机制**：提取的 URL 与检索结果的 source 列表做精确匹配，
   标记 is_valid=True/False，帮助调用方区分 LLM 幻觉产生的虚假引用。

3. **结构化输出知识演示**：_extract_structured 方法展示了
   with_structured_output 的用法，这是面试重点知识点。
   但作为默认策略过于重量级（额外 LLM 调用），正则解析是生产级首选。

使用示例：
    extractor = CitationExtractor()

    # 正则策略（默认）
    citations = extractor.extract(answer_text, source_urls)

    # 结构化输出策略（可选）
    extractor = CitationExtractor(llm=my_llm, use_structured_output=True)
    citations = extractor.extract(answer_text, source_urls)
"""

import re
from dataclasses import dataclass
from typing import ClassVar, List, Optional

import structlog
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from .exceptions import CitationExtractionError

logger = structlog.get_logger(__name__)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Citation:
    """单个引用信息。

    Attributes:
        number: 引用编号，对应回答文本中的 [N] 标记
        url: 引用指向的文档 URL
    """
    number: int
    url: str


@dataclass
class ValidatedCitation(Citation):
    """带验证结果的引用。

    Attributes:
        is_valid: URL 是否存在于检索结果的 source 列表中。
            True = 引用的 URL 确实来自检索到的文档（可信引用）
            False = URL 不在检索结果中（可能是 LLM 幻觉产生的虚假引用）
    """
    is_valid: bool


# ============================================================
# 结构化输出的 Pydantic Schema
# ============================================================

class CitationItem(BaseModel):
    """单个引用条目（结构化输出的 schema 定义）。

    为什么用 Pydantic 而非 dataclass：
        with_structured_output 要求传入 Pydantic BaseModel，
        LangChain 内部使用 Pydantic 的 JSON Schema 生成 Function Calling 的
        parameters 定义。dataclass 不支持此功能。
    """
    number: int = Field(description="引用编号，对应回答中的 [N] 标记")
    url: str = Field(description="引用的文档 URL")


class CitationList(BaseModel):
    """引用列表（结构化输出的顶层 schema）。

    为什么需要顶层容器：
        with_structured_output 返回的是单个 Pydantic 对象，
        不能直接返回 List。需要一个包含列表字段的容器类。
    """
    citations: List[CitationItem] = Field(description="从回答中提取的所有引用")


# ============================================================
# 引用提取 Prompt（结构化输出策略专用）
# ============================================================

CITATION_EXTRACTION_PROMPT = """从以下回答文本中提取所有引用信息。

回答文本：
{answer}

请提取文本中所有 [N] URL 格式的引用，返回每个引用的编号和URL。"""


# ============================================================
# CitationExtractor 类
# ============================================================

class CitationExtractor:
    """引用提取与验证器，支持正则解析和结构化输出两种策略。

    策略选择逻辑：
        use_structured_output=False（默认）→ 直接调用 _extract_regex
        use_structured_output=True → 先尝试 _extract_structured，
            若模型不支持 Function Calling（抛出 NotImplementedError），
            则回退到 _extract_regex 并记录 warning 日志

    Args:
        llm: Chat 模型实例（仅结构化输出策略需要，正则策略可传 None）
        use_structured_output: 是否优先使用结构化输出策略，默认 False
    """

    # 正则模式：匹配 [N] URL 格式的引用
    # 具体做法：
    #   \[(\d+)\]    匹配 [1] [2] 等编号，捕获数字
    #   \s*           匹配编号和 URL 之间可能的空白
    #   (https?://\S+) 匹配以 http:// 或 https:// 开头的 URL，\S+ 匹配非空白字符
    # 为什么不用更复杂的正则：
    #   Prompt 规定的格式很规范（[N] URL 每行一个），
    #   过于复杂的正则反而容易误匹配回答正文中的 [N] 标记
    #   （正文中 [1] 后面通常是中文文字而非 URL）
    CITATION_PATTERN: ClassVar[str] = r"\[(\d+)\]\s*(https?://\S+)"

    def __init__(
        self,
        llm: Optional[BaseChatModel] = None,
        use_structured_output: bool = False,
    ):
        # 保存 llm 引用（结构化输出策略使用）
        self._llm = llm
        # 保存策略配置
        self._use_structured_output = use_structured_output

        # 如果启用结构化输出但未提供 llm，记录 warning 并回退到正则策略
        # 为什么不抛异常：正则策略已足够可靠，结构化输出是增强而非必需
        if use_structured_output and llm is None:
            logger.warning(
                "启用结构化输出但未提供 LLM，回退到正则策略",
                use_structured_output=use_structured_output,
                llm_provided=False,
            )
            self._use_structured_output = False

    def extract(
        self, answer: str, sources: List[str]
    ) -> List[ValidatedCitation]:
        """从回答文本中提取引用并验证。

        为什么提取失败返回空列表而非抛异常：
            引用提取是增强功能，不应中断主流程。
            调用方（RAGChain）在捕获 CitationExtractionError 后
            也会返回 citations=[] 的 RAGResponse。

        Args:
            answer: LLM 生成的回答文本
            sources: 检索命中的文档 source URL 列表

        Returns:
            验证后的引用列表。提取失败返回空列表。
        """
        # 第1步：边界处理 — answer 为空 → 返回空列表
        if not answer or not answer.strip():
            logger.debug("回答为空，跳过引用提取")
            return []

        # 第2步：根据策略选择提取方法
        try:
            if self._use_structured_output:
                # 先尝试结构化输出，失败回退正则
                try:
                    citations = self._extract_structured(answer, sources)
                    logger.info(
                        "引用提取完成（结构化输出策略）",
                        citation_count=len(citations),
                        valid_count=sum(1 for c in citations if c.is_valid),
                    )
                    return citations
                except (NotImplementedError, Exception) as e:
                    # 模型不支持 Function Calling 或其他异常，回退到正则
                    logger.warning(
                        "结构化输出失败，回退到正则策略",
                        error=str(e),
                        error_type=type(e).__name__,
                    )

            # 正则策略（默认或回退）
            citations = self._extract_regex(answer, sources)
            logger.info(
                "引用提取完成（正则策略）",
                citation_count=len(citations),
                valid_count=sum(1 for c in citations if c.is_valid),
            )
            return citations

        except CitationExtractionError:
            # 已知的引用提取异常，直接向上抛出
            raise
        except Exception as e:
            # 未知异常，包装为 CitationExtractionError
            logger.error("引用提取未知异常", error=str(e))
            raise CitationExtractionError(
                f"引用提取失败: {e}"
            ) from e

    def _extract_regex(
        self, answer: str, sources: List[str]
    ) -> List[ValidatedCitation]:
        """正则提取策略。

        具体做法：
            1. 使用 self.CITATION_PATTERN 对 answer 进行 findall
               → 得到 List[Tuple[str, str]]，每个元素是 (编号, URL)
            2. URL 清理：rstrip(")") rstrip(".") 去除尾部可能被误捕获的标点
               #   正则 \\S+ 会捕获 URL 末尾紧跟的 ) 或 .
               如 "https://example.com/)" 中的右括号
            3. 构建 ValidatedCitation：
               number = int(编号), url = 清理后的 URL,
               is_valid = url in sources_set（sources 预先转为集合做 O(1) 查找）
            4. 去重：同一 (number, url) 只保留第一个
               为什么需要去重：LLM 可能在回答正文中和来源列表中
               各出现一次 [1] URL，正则会匹配到两次
            5. 按 number 排序后返回

        Args:
            answer: LLM 生成的回答文本
            sources: 检索结果 source URL 列表

        Returns:
            验证后的引用列表
        """
        # 第1步：将 sources 转为集合，O(1) 查找
        sources_set = set(sources)

        # 第2步：re.findall 匹配所有 [N] URL 模式
        matches = re.findall(self.CITATION_PATTERN, answer)

        if not matches:
            logger.debug("正则未匹配到任何引用", answer_length=len(answer))
            return []

        # 第3步：遍历匹配结果，清理 URL、构建 ValidatedCitation、去重
        seen: set = set()  # 用于去重：(number, url) 元组
        citations: List[ValidatedCitation] = []

        for num_str, url in matches:
            # URL 清理：去除尾部可能被误捕获的标点
            # 为什么按此顺序清理：先去 ) 再去 .，
            # 避免 "https://example.com/)." 变成 "https://example.com/"
            cleaned_url = url.rstrip(")").rstrip(".")

            number = int(num_str)
            key = (number, cleaned_url)

            # 去重：同一 (number, url) 只保留第一个
            if key in seen:
                continue
            seen.add(key)

            # 构建 ValidatedCitation，验证 URL 是否存在于检索结果中
            is_valid = self._validate_url(cleaned_url, sources_set)
            citations.append(ValidatedCitation(
                number=number,
                url=cleaned_url,
                is_valid=is_valid,
            ))

        # 第4步：按 number 排序
        citations.sort(key=lambda c: c.number)

        # 第5步：记录日志
        logger.debug(
            "正则提取完成",
            raw_matches=len(matches),
            unique_citations=len(citations),
            valid_count=sum(1 for c in citations if c.is_valid),
        )

        return citations

    def _extract_structured(
        self, answer: str, sources: List[str]
    ) -> List[ValidatedCitation]:
        """结构化输出策略（可选增强）。

        具体做法：
            1. 用 self._llm.with_structured_output(CitationList) 创建结构化链
               为什么用 with_structured_output：
                   让 LLM 返回符合 CitationList schema 的 JSON 对象，
                   LangChain 内部自动将 schema 转为 Function Calling 的
                   parameters 定义，解析返回的 JSON 为 Pydantic 对象。
            2. 构建提取 Prompt，填入 answer 文本
            3. 调用结构化链的 invoke 方法
            4. 将 CitationList.citations 转为 List[ValidatedCitation]，
               对每个 url 做 is_valid 验证
            5. 异常处理：
               NotImplementedError → 模型不支持 Function Calling，回退到正则
               其他异常 → 包装为 CitationExtractionError 并抛出

        为什么不在主 RAG 链中使用 with_structured_output：
            结构化输出要求 LLM 返回 JSON 而非自由文本，
            与流式输出不兼容（JSON 无法逐 token 流式传输）。
            因此结构化输出仅用于引用提取（后处理步骤），
            不用于主链的回答生成。

        Args:
            answer: LLM 生成的回答文本
            sources: 检索结果 source URL 列表

        Returns:
            验证后的引用列表

        Raises:
            CitationExtractionError: 结构化输出解析失败时
        """
        # 第1步：边界检查 — self._llm 为 None → 回退到 _extract_regex 并记录 warning
        if self._llm is None:
            logger.warning("结构化输出策略需要 LLM，但未提供，回退到正则策略")
            return self._extract_regex(answer, sources)

        sources_set = set(sources)

        try:
            # 第2步：创建结构化链
            # with_structured_output 内部会尝试使用 Function Calling，
            # 如果模型不支持会抛出 NotImplementedError
            structured_llm = self._llm.with_structured_output(CitationList)

            # 第3步：构建提取 Prompt，填入 answer
            prompt_text = CITATION_EXTRACTION_PROMPT.format(answer=answer)

            # 第4步：调用结构化链
            result = structured_llm.invoke(prompt_text)

            # 第5步：将 CitationList → List[ValidatedCitation]（含 is_valid 验证）
            citations: List[ValidatedCitation] = []
            for item in result.citations:
                is_valid = self._validate_url(item.url, sources_set)
                citations.append(ValidatedCitation(
                    number=item.number,
                    url=item.url,
                    is_valid=is_valid,
                ))

            # 按 number 排序
            citations.sort(key=lambda c: c.number)

            logger.debug(
                "结构化输出提取完成",
                citation_count=len(citations),
                valid_count=sum(1 for c in citations if c.is_valid),
            )

            return citations

        except NotImplementedError:
            # 模型不支持 Function Calling，向上抛出让 extract() 回退到正则
            raise
        except Exception as e:
            # 其他异常，包装为 CitationExtractionError
            raise CitationExtractionError(
                f"结构化输出引用提取失败: {e}"
            ) from e

    def _validate_url(self, url: str, sources_set: set) -> bool:
        """验证 URL 是否存在于检索结果的 source 集合中。

        为什么需要验证：
            LLM 可能产生"幻觉引用"——引用了文档库中不存在的 URL。
            验证后的 is_valid 字段帮助调用方区分真实引用和幻觉引用。

        验证方式：
            精确匹配（url in sources_set）。
            为什么不做模糊匹配（如域名匹配、路径前缀匹配）：
                当前文档库的 source URL 是完整路径，LLM 通常完整复制，
                精确匹配即可。若后续出现 URL 格式不一致问题，
                可升级为归一化匹配（去除尾部斜杠、统一 http/https）。

        Args:
            url: 待验证的 URL
            sources_set: 检索结果 source URL 集合

        Returns:
            True = URL 存在于检索结果中
        """
        return url in sources_set
