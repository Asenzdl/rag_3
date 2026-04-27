"""数据爬取脚本：爬取langchain文档并保存为markdown文件"""
import json

from langchain_community.document_loaders import SitemapLoader
import re
import os
from bs4 import BeautifulSoup, Doctype, NavigableString, Tag, Comment
from typing import Generator
from typing import Optional

# ========== 配置 ==========
SITEMAP_URL = "https://docs.langchain.com/sitemap.xml"
FILTER_URLS = ["https://docs.langchain.com/oss/python/langchain/"]
OUTPUT_DIR = "data/langchain_python_separated"
FILTER_FLAG = True

# 需要移除的元素配置
# 按标签名移除
TAGS_TO_REMOVE = [

]
# 按 class 名移除
CLASSES_TO_REMOVE = [
    "source-links",
]
# 按 ID 移除
IDS_TO_REMOVE = [

]
# 按 role 属性移除
ROLES_TO_REMOVE = [

]
# 按文本内容移除
TEXT_PATTERNS_TO_REMOVE = [
    r"⌘",
    r"\$\!\$",
]

# bs4处理
def clean_text(text: str) -> str:
    """清理文本中的特殊字符"""
    if not text:
        return ""
    # 移除零宽空格和其他控制字符
    text = re.sub(r'[\u200b\u200c\u200d\ufeff\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    # 规范化空白字符
    text = re.sub(r'[\t\xa0]', ' ', text)
    return text.strip()


def should_remove_by_class(element) -> bool:
    """检查元素是否应该根据class被移除"""
    if not isinstance(element, Tag):
        return False
    classes = element.get("class", [])
    if not classes:
        return False
    class_str = " ".join(classes) if isinstance(classes, list) else str(classes)
    class_str_lower = class_str.lower()
    return any(cls in class_str_lower for cls in CLASSES_TO_REMOVE)


def remove_unwanted_elements(soup: BeautifulSoup) -> None:
    """移除不需要的元素"""
    # 按标签名移除
    for tag_name in TAGS_TO_REMOVE:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # 按class移除
    for tag in soup.find_all(should_remove_by_class):
        tag.decompose()

    # 按ID移除
    for id_name in IDS_TO_REMOVE:
        for tag in soup.find_all(id=id_name):
            tag.decompose()

    # 按role移除
    for role_name in ROLES_TO_REMOVE:
        for tag in soup.find_all(attrs={"role": role_name}):
            tag.decompose()

    # 按文本模式移除
    for pattern in TEXT_PATTERNS_TO_REMOVE:
        for tag in soup.find_all(string=re.compile(pattern, re.IGNORECASE)):
            if tag.parent:
                tag.parent.decompose()

    # 移除HTML注释
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()


def extract_main_content(soup: BeautifulSoup) -> Optional[BeautifulSoup]:
    """提取主内容区域"""
    selectors = [
        ("div", {"id": "content"}),
        ("article", None),
        ("main", None),
        ("div", {"class": "content"}),
        ("div", {"class": "mdx-content"}),
        ("div", {"class": "prose"}),
    ]

    for tag_name, attrs in selectors:
        element = soup.find(tag_name, attrs) if attrs else soup.find(tag_name)
        if element:
            return element

    return soup.find("body") or soup


# 1. 定义内容提取器：将 HTML 转换为 Markdown 格式
def langchain_docs_extractor(soup: BeautifulSoup) -> str:
    """
    提取文档内容的核心逻辑：
    1. 获取 <head> 中的 <h1> 标题
    2. 获取 <div id="content"> 中的主体内容
    3. 排除导航、页脚、source-links 等无关内容
    """
    output_parts = []
    # ========== 第一步：提取 <header> 中的 <h1> 标题 ==========
    header = soup.find("header")
    if header:
        h1 = header.find("h1")
        if h1:
            output_parts.append(f"# {h1.get_text(strip=True)}\n\n")
    # ========== 第二步：获取 <div id="content"> 主体内容 ==========
    content_soup = extract_main_content(soup)
    # ========== 第三步：在内容区域内移除无关元素 ==========
    remove_unwanted_elements(content_soup)

    def get_text(tag: Tag) -> Generator[str, None, None]:
        for child in tag.children:
            if isinstance(child, Doctype):
                continue
            if isinstance(child, NavigableString):
                yield child
            elif isinstance(child, Tag):
                # 标题处理
                if child.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                    yield f"{'#' * int(child.name[1:])} {child.get_text()}\n\n"
                # 链接处理
                elif child.name == "a":
                    yield f"[{child.get_text(strip=False)}]({child.get('href')})"
                # 图片处理
                elif child.name == "img":
                    yield f"![{child.get('alt', '')}]({child.get('src')})"
                # 文本样式处理 (加粗、斜体)
                elif child.name in ["strong", "b"]:
                    yield f"**{child.get_text(strip=False)}**"
                elif child.name in ["em", "i"]:
                    yield f"_{child.get_text(strip=False)}_"
                # 换行处理
                elif child.name == "br":
                    yield "\n"
                # 分隔线处理
                elif child.name == "hr":
                    yield "\n\n---\n\n"
                # 代码块处理 (保留语言标识)
                elif child.name == "code":
                    # 查找最近的 pre 祖先（支持多层嵌套）
                    parent = child.find_parent("pre")
                    if parent is not None:
                        # 从 <code> 的 language 属性中获取 (如 <code language="python">)
                        language = child.attrs.get("language", "")
                        code_content = child.get_text()
                        # 清理代码内容首尾空行
                        code_content = code_content.strip()

                        if language:
                            yield f"\n```{language}\n{code_content}\n```\n\n"
                        else:
                            yield f"```\n{code_content}\n```\n\n"
                    else:
                        # 行内代码
                        yield f"`{child.get_text(strip=False)}`"
                # 段落处理
                elif child.name == "p":
                    yield from get_text(child)
                    yield "\n\n"
                # 列表处理 (无序、有序)
                elif child.name == "ul":
                    for li in child.find_all("li", recursive=False):
                        yield "- "
                        yield from get_text(li)
                        yield "\n\n"
                elif child.name == "ol":
                    for i, li in enumerate(child.find_all("li", recursive=False)):
                        yield f"{i + 1}. "
                        yield from get_text(li)
                        yield "\n\n"
                # 特殊组件处理 (如文档中的 Tab 选项卡)
                elif child.name == "div" and "tabs-container" in child.attrs.get("class", [""]):
                    tabs = child.find_all("li", {"role": "tab"})
                    tab_panels = child.find_all("div", {"role": "tabpanel"})
                    for tab, tab_panel in zip(tabs, tab_panels):
                        tab_name = tab.get_text(strip=True)
                        yield f"{tab_name}\n"
                        yield from get_text(tab_panel)
                # 表格处理
                elif child.name == "table":
                    yield "\n"
                    thead = child.find("thead")
                    header_exists = isinstance(thead, Tag)
                    if header_exists:
                        headers = thead.find_all("th")
                        if headers:
                            yield "| "
                            yield " | ".join(header.get_text() for header in headers)
                            yield " |\n"
                            yield "| "
                            yield " | ".join("----" for _ in headers)
                            yield " |\n"

                    tbody = child.find("tbody")
                    tbody_exists = isinstance(tbody, Tag)
                    if tbody_exists:
                        for row in tbody.find_all("tr"):
                            yield "| "
                            yield " | ".join(cell.get_text(strip=True) for cell in row.find_all("td"))
                            yield " |\n"
                    yield "\n\n"
                # 忽略按钮等交互元素
                elif child.name in ["button", "input", "select", "textarea", "form"]:
                    continue
                # 忽略包含特定 class 的元素（广告、提示框等）
                elif child.name == "div" and any(
                    cls in str(child.get("class", [])).lower()
                    for cls in ["advertisement", "ad-", "promo", "announcement-banner"]
                ):
                    continue
                else:
                    yield from get_text(child)

    # ========== 第四步：提取并合并内容 ==========
    content_text = "".join(get_text(content_soup))
    output_parts.append(content_text)

    joined = "".join(output_parts)
    # return re.sub(r"\n\n+", "\n\n", joined).strip()
    return clean_text(re.sub(r"\n\n+", "\n\n", joined).strip())

def metadata_extractor(meta: dict, soup: BeautifulSoup) -> dict:
    """提取元数据"""
    title = soup.find("title")
    title = title.get_text().removesuffix(" - Docs by LangChain") if title else ""
    description = soup.find("meta", attrs={"name": "description"})
    description = description.get("content", "") if description else ""
    html = soup.find("html")
    language = html.get("lang", "") if html else ""
    return {
        "source": meta["loc"],
        "title": title,
        "description": description,
        "language": language,
        **meta,
    }

def load_langchain_docs():
    """加载LangChain文档"""
    print("开始爬取文档...")
    docs = SitemapLoader(
        SITEMAP_URL,
        filter_urls=FILTER_URLS if FILTER_FLAG else None,
        parsing_function=langchain_docs_extractor,
        default_parser="lxml",
        meta_function=metadata_extractor,
    ).load()
    print(f"成功加载 {len(docs)} 个文档")
    return docs


def save_documents(docs, output_folder="langchain_docs_separated"):
    """保存文档为markdown文件，按source路径分级存储，生成JSON索引"""
    os.makedirs(output_folder, exist_ok=True)
    
    # 第一遍：统计每个目录节点下的直接子项集合
    # dir_children: {parent_path: set(直接子名称)}
    # parent_path 为空字符串表示根节点
    dir_children = {}  # {parent_path: set}
    doc_path_mapping = []
    
    for i, doc in enumerate(docs):
        source_url = doc.metadata.get("source", "")
        path_from_url = source_url.replace("https://docs.langchain.com/", "").rstrip("/")
        
        if not path_from_url:
            path_from_url = f"uncategorized/doc_{i}"
        
        doc_path_mapping.append((i, doc, path_from_url))
        
        # 记录每个祖先目录的直接子项
        parts = path_from_url.split('/')
        for level in range(len(parts)):
            parent = '/'.join(parts[:level])  # level=0 时为空字符串（根）
            child = parts[level]
            if parent not in dir_children:
                dir_children[parent] = set()
            dir_children[parent].add(child)
    
    # 第二遍：保存文档
    # 根据 dir_children 找到每个路径的最佳存放层：
    # 从根往下，找到最深的「有多个直接子项」的目录层，文件放在这里
    metadata_index = []
    
    for i, doc, path_from_url in doc_path_mapping:
        try:
            parts = path_from_url.split('/')
            
            # 从根往下扫描，找到最深的「有多个直接子项」的目录层
            # anchor_level: 文件保存在 parts[:anchor_level] 对应目录下
            # 文件名 = parts[anchor_level:] 用 _ 拼接
            anchor_level = 0
            for level in range(len(parts)):
                parent = '/'.join(parts[:level])  # level=0 时为空字符串
                children_count = len(dir_children.get(parent, set()))
                if children_count > 1:
                    # 该层有多个子项，更新锚点（继续向下寻找更深的）
                    anchor_level = level
                # 单子项层无意义，继续向下扫描
            
            # 文件放在 anchor_level 对应目录，文件名用剩余路径段拼接
            if anchor_level > 0:
                target_dir = os.path.join(output_folder, *parts[:anchor_level])
            else:
                target_dir = output_folder
            os.makedirs(target_dir, exist_ok=True)
            remaining_parts = parts[anchor_level:]
            filename = f"{'_'.join(remaining_parts)}.md"
            
            filepath = os.path.join(target_dir, filename)
            
            # 处理文件名冲突
            counter = 1
            original_filename = filename
            while os.path.exists(filepath):
                name_without_ext = os.path.splitext(original_filename)[0]
                ext = os.path.splitext(original_filename)[1]
                filename = f"{name_without_ext}_{counter}{ext}"
                filepath = os.path.join(target_dir, filename)
                counter += 1
            
            # 构建带元数据的markdown内容（值加引号防止 YAML 特殊字符破坏格式）
            metadata_yaml = "---\n"
            for key, value in doc.metadata.items():
                # 对值加双引号并转义内部双引号，防止 : # 等字符破坏 YAML
                escaped_value = str(value).replace('"', '\\"')
                metadata_yaml += f'{key}: "{escaped_value}"\n'
            metadata_yaml += "---\n\n"
            
            # 写入文件
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(metadata_yaml)
                f.write(doc.page_content)
            
            # 记录元数据索引
            relative_path = os.path.relpath(filepath, output_folder)
            metadata_index.append({
                "id": i,
                "source": doc.metadata.get("source", ""),
                "file_path": relative_path,
                "title": doc.metadata.get("title", ""),
                "description": doc.metadata.get("description", ""),
            })
            
            if (i + 1) % 10 == 0:
                print(f"已保存 {i + 1}/{len(docs)} 个文档...")
        
        except Exception as e:
            print(f"保存文档 {i} 失败: {e}")
            continue
    
    # 保存JSON索引文件
    index_file = os.path.join(output_folder, "metadata_index.json")
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(metadata_index, f, ensure_ascii=False, indent=2)
    
    print(f"\n完成! 共保存 {len(docs)} 个文档到 {output_folder}")
    print(f"元数据索引已保存到: {index_file}")


def main():
    """主函数"""
    # 设置 USER_AGENT
    os.environ.setdefault("USER_AGENT",
                          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # 爬取文档
    docs = load_langchain_docs()

    # 保存文档
    print("\n开始保存文档...")
    save_documents(docs, OUTPUT_DIR)


if __name__ == '__main__':
    main()
