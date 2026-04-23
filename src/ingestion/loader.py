"""文档加载与 metadata 整合模块。

职责：
- 读取 Markdown 文件并解析 YAML frontmatter
- 加载目录下所有文档（支持多目录 + 排除子目录）
- 整合 metadata_index.json 中的补充字段
"""

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Union
from urllib.parse import urlparse

import frontmatter
from langchain_core.documents import Document


# ============================================================
# 文档加载（解析 YAML frontmatter）
# ============================================================

def _generate_doc_id(source_url: str) -> str:
    """基于 source URL 生成稳定的 16 位十六进制唯一标识。"""
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]


def load_markdown_with_frontmatter(file_path: str, encoding: str = "utf-8") -> Document:
    """读取单个 Markdown 文件，解析 YAML frontmatter 作为 metadata，
    纯正文（去掉 frontmatter）作为 page_content。
    """
    with open(file_path, "r", encoding=encoding) as f:
        post = frontmatter.load(f)

    # frontmatter 中的字段 -> metadata
    metadata = dict(post.metadata)  # source, title, description, language, lastmod …
    metadata["file_path"] = str(file_path)

    # 移除 loc（与 source 重复）
    metadata.pop("loc", None)

    # 基于 source URL 生成稳定的 doc_id
    source_url = metadata.get("source", "")
    if source_url:
        metadata["doc_id"] = _generate_doc_id(source_url)

    return Document(page_content=post.content, metadata=metadata)


def load_directory(
    directories: Union[str, List[str]],
    glob_pattern: str = "**/*.md",
    exclude_dirs: Optional[List[str]] = None,
) -> List[Document]:
    """加载一个或多个目录下的 Markdown 文件，支持排除指定子目录。

    Args:
        directories: 单个目录路径或目录路径列表。
        glob_pattern: 文件匹配模式，默认递归匹配所有 .md 文件。
        exclude_dirs: 需要排除的子目录路径列表（相对于对应 directory）。
            例如 ["frontend", "integrations"] 会排除所有目录下匹配的子路径。

    Examples:
        # 单目录加载
        docs = load_directory("data/langchain_python_separated")

        # 多目录加载
        docs = load_directory([
            "data/langchain_python_separated/oss/python/langchain",
            "data/langchain_python_separated/oss/python/langgraph",
        ])

        # 多目录 + 排除子目录
        docs = load_directory(
            directories=[
                "data/langchain_python_separated/oss/python/langchain",
                "data/langchain_python_separated/oss/python/langgraph",
            ],
            exclude_dirs=["frontend", "integrations"],
        )
    """
    if isinstance(directories, str):
        directories = [directories]

    # 预处理排除路径：统一为绝对路径集合
    excluded_paths: List[Path] = []
    if exclude_dirs:
        for d in directories:
            for ex in exclude_dirs:
                ex_path = (Path(d) / ex).resolve()
                excluded_paths.append(ex_path)

    def _is_excluded(file_path: Path) -> bool:
        """检查文件是否在排除目录下。"""
        resolved = file_path.resolve()
        return any(resolved.is_relative_to(ep) for ep in excluded_paths)

    docs = []
    seen_paths: set = set()  # 多目录可能有重叠，去重

    for directory in directories:
        for md_path in Path(directory).glob(glob_pattern):
            resolved = md_path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            if excluded_paths and _is_excluded(md_path):
                continue

            try:
                doc = load_markdown_with_frontmatter(str(md_path))
                docs.append(doc)
            except Exception as e:
                print(f"[WARN] 跳过文件 {md_path}: {e}")

    if excluded_paths:
        print(f"  排除目录: {[str(p) for p in excluded_paths]}")
    print(f"  共加载 {len(docs)} 篇文档（来自 {len(directories)} 个目录）")
    return docs


# ============================================================
# metadata_index.json 整合
# ============================================================

def _parse_doc_category(source_url: str) -> str:
    """从 source URL 解析文档分类。
    例如:
      https://docs.langchain.com/langsmith/abac        -> langsmith
      https://docs.langchain.com/api-reference/...      -> api-reference
      https://docs.langchain.com/oss/python/langchain/… -> oss/python
    """
    path = urlparse(source_url).path.strip("/")
    parts = path.split("/")
    if not parts:
        return "unknown"
    # api-reference 保留一级
    if parts[0] == "api-reference":
        return "api-reference"
    # oss/python 保留两级
    if parts[0] == "oss" and len(parts) > 1:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def load_metadata_index(json_path: str) -> Dict[str, dict]:
    """加载 metadata_index.json，返回 file_path -> metadata 映射。
    注意：不再使用 JSON 中的递增 id，doc_id 由 source URL 哈希生成。
    """
    with open(json_path, "r", encoding="utf-8") as f:
        entries = json.load(f)
    mapping: Dict[str, dict] = {}
    for entry in entries:
        # 统一路径分隔符为 /
        fp = entry["file_path"].replace("\\\\", "/").replace("\\", "/")
        mapping[fp] = {
            "source": entry.get("source", ""),
            "title": entry.get("title", ""),
            "description": entry.get("description", ""),
        }
    return mapping


def _infer_doc_type(source_url: str) -> str:
    """基于 URL 路径规则推导文档类型。
    返回: 'api-reference' | 'tutorial' | 'guide'
    """
    path = urlparse(source_url).path.strip("/")
    if path.startswith("api-reference"):
        return "api-reference"
    if "/how-to" in path or "/tutorials" in path:
        return "tutorial"
    return "guide"


def enrich_docs_with_index(
    docs: List[Document],
    metadata_index: Dict[str, dict],
    data_dir: str,
) -> List[Document]:
    """将 metadata_index.json 中的字段合并到每个 Document 的 metadata 中。
    合并策略：frontmatter 优先，JSON 补充缺失字段。
    """
    data_dir_path = Path(data_dir).resolve()
    for doc in docs:
        # 计算相对路径，用于匹配 JSON 中的 file_path
        abs_path = Path(doc.metadata.get("file_path", "")).resolve()
        try:
            rel_path = abs_path.relative_to(data_dir_path).as_posix()
        except ValueError:
            rel_path = ""

        index_meta = metadata_index.get(rel_path, {})

        # frontmatter 优先，JSON 补充缺失
        for key in ("source", "title", "description"):
            if not doc.metadata.get(key) and index_meta.get(key):
                doc.metadata[key] = index_meta[key]

        # 若 frontmatter 没有 source 但 JSON 有，补充后生成 doc_id
        source_url = doc.metadata.get("source", "")
        if source_url and "doc_id" not in doc.metadata:
            doc.metadata["doc_id"] = _generate_doc_id(source_url)

        # 解析 doc_category 和 doc_type
        if source_url:
            doc.metadata["doc_category"] = _parse_doc_category(source_url)
            doc.metadata["doc_type"] = _infer_doc_type(source_url)

    return docs
