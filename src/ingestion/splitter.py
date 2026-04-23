"""智能文档切分模块。

职责：
- 按 Markdown 标题（h1/h2）进行第一阶段切分
- 代码块边界保护，确保 ``` 块不被截断
- 超大段递归字符切分
- 传播文档级 + 标题级 metadata
"""

import re
from typing import List, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


HEADERS_TO_SPLIT_ON = [
    ("#", "h1"),
    ("##", "h2"),
]


class SmartDocumentSplitter:
    """智能文档切分器：标题切分 + 代码块保护 + 递归字符切分。"""

    def __init__(self, chunk_size: int = 2000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=HEADERS_TO_SPLIT_ON
        )
        self.recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=[
                "\n```\n",  # 代码块结束标记
                "\n```",
                "\n\n",    # 段落
                "\n",      # 行
                ".", "!", "?", ";",
                " ",
                ""
            ],
            length_function=len,
        )

    @staticmethod
    def _protect_code_blocks(text: str, chunk_size: int) -> List[str]:
        """按代码块边界将文本切分为安全段，确保代码块不被截断。

        策略：
        1. 用正则找出所有 ```...``` 代码块的位置
        2. 在代码块边界之间的「文本段」处切分（而非在代码块内部）
        3. 如果「说明文字 + 紧跟的代码块」总长 < chunk_size，合并为一段
        4. 如果单个代码块本身超过 chunk_size，保持完整（后续递归切分会处理）

        Returns:
            字符串列表，每个元素是一个"安全段"（代码块完整不被截断）
        """
        if not text.strip():
            return []

        # 找出所有代码块的起止位置
        code_blocks = list(re.finditer(r'```[\w]*\n[\s\S]*?```', text))

        if not code_blocks:
            # 没有代码块，直接返回原文本
            return [text]

        segments = []
        last_end = 0

        for match in code_blocks:
            code_start = match.start()
            code_end = match.end()

            # 代码块之前的文本
            text_before = text[last_end:code_start]

            if text_before.strip():
                # 判断「前置文本 + 代码块」是否可以合并
                combined = text_before + text[code_start:code_end]
                if len(combined) <= chunk_size:
                    # 合并为一段
                    segments.append(combined)
                else:
                    # 分别添加：先加文本，再加代码块
                    segments.append(text_before)
                    segments.append(text[code_start:code_end])
            else:
                # 没有前置文本，直接添加代码块
                segments.append(text[code_start:code_end])

            last_end = code_end

        # 处理最后一个代码块之后的文本
        if last_end < len(text):
            remaining = text[last_end:]
            if remaining.strip():
                segments.append(remaining)

        return segments

    def smart_split(self, documents: List[Document]) -> List[Document]:
        """切分文档：
        第一阶段 → 标题切分（仅 h1/h2）
        第二阶段 → 代码块保护 + 递归切分
        """
        final_chunks: List[Document] = []

        for doc in documents:
            # 保存文档级 metadata（source, title, doc_id 等）
            doc_meta = dict(doc.metadata)

            # 第一阶段：按标题切分
            header_chunks = self.markdown_splitter.split_text(doc.page_content)

            chunk_index = 0
            for chunk in header_chunks:
                # 第二阶段：代码块保护 + 递归切分
                # 先用 _protect_code_blocks 得到安全段
                safe_segments = self._protect_code_blocks(
                    chunk.page_content, self.chunk_size
                )

                for segment in safe_segments:
                    # 对每个安全段调用递归切分
                    # RecursiveCharacterTextSplitter 会自动判断是否需要切分
                    sub_chunks = self.recursive_splitter.split_text(segment)

                    for sub_chunk in sub_chunks:
                        # 合并：文档级 meta + 标题层级 meta（h1-h2）
                        merged = {**doc_meta, **chunk.metadata}
                        merged["chunk_index"] = chunk_index

                        # 检测代码块信息
                        has_code, code_language = _extract_code_info(sub_chunk)
                        merged["has_code"] = has_code
                        merged["code_language"] = code_language

                        final_chunks.append(Document(
                            page_content=sub_chunk,
                            metadata=merged
                        ))
                        chunk_index += 1

        return final_chunks


def _extract_code_info(content: str) -> Tuple[bool, str]:
    """检测 chunk 中的代码块，返回 (has_code, code_language)。
    code_language 为逗号分隔的去重排序语言列表。
    """
    code_blocks = re.findall(r"```(\w*)", content)
    has_code = len(code_blocks) > 0
    languages = sorted(set(lang for lang in code_blocks if lang))
    return has_code, ",".join(languages) if languages else ""
