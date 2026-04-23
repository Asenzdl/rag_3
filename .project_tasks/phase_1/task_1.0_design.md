# Task 1.0 知识库数据集构建 - 实现文档

## 第 1 层：代码骨架

### 模块结构

```
src/craw_html_to_md.py   # 单文件脚本，爬取 + 转换 + 保存
```

### 核心函数签名

```python
# ===== 配置层（模块级常量）=====
SITEMAP_URL: str          # "https://docs.langchain.com/sitemap.xml"
FILTER_URLS: list[str]    # URL 过滤前缀列表
OUTPUT_DIR: str            # 输出目录路径
FILTER_FLAG: bool          # 是否启用 URL 过滤

# ===== HTML 清理层 =====
def clean_text(text: str) -> str:
    """移除零宽字符、规范化空白"""

def should_remove_by_class(element: Tag) -> bool:
    """按 class 名判断元素是否应被移除"""

def remove_unwanted_elements(soup: BeautifulSoup) -> None:
    """批量移除不需要的 HTML 元素（标签/class/id/role/文本模式/注释）"""

def extract_main_content(soup: BeautifulSoup) -> Optional[BeautifulSoup]:
    """按优先级选择器（#content > article > main > ...）提取主内容区域"""

# ===== 核心转换层 =====
def langchain_docs_extractor(soup: BeautifulSoup) -> str:
    """HTML → Markdown 核心转换器（SitemapLoader 的 parsing_function）
    内部嵌套 get_text() 生成器递归遍历 DOM 树，处理：
    标题/链接/图片/加粗斜体/代码块/段落/列表/表格/Tab组件"""

def metadata_extractor(meta: dict, soup: BeautifulSoup) -> dict:
    """提取 title / description / language 等元数据"""

# ===== 编排层 =====
def load_langchain_docs() -> list[Document]:
    """调用 SitemapLoader 执行爬取"""

def save_documents(docs: list[Document], output_folder: str) -> None:
    """按 URL 路径分级保存为 .md 文件 + JSON 索引"""

def main() -> None:
    """入口：设置 UA → 爬取 → 保存"""
```

### 模块依赖关系

```
SitemapLoader (langchain_community)
    ├── parsing_function → langchain_docs_extractor()
    │       ├── extract_main_content()
    │       ├── remove_unwanted_elements()
    │       └── clean_text()
    └── meta_function → metadata_extractor()

main()
    ├── load_langchain_docs() → SitemapLoader.load()
    └── save_documents() → 文件系统写入 + JSON 索引
```

---

## 第 2 层：架构设计思路

### 为什么用 SitemapLoader？

SitemapLoader 是 LangChain 社区提供的文档加载器，核心优势：
- **基于 sitemap.xml 发现所有页面**：不需要手动维护 URL 列表，sitemap 是站点的"目录"
- **内置并发爬取**：底层用 `requests` + 线程池，比手写爬虫省力
- **插拔式解析**：`parsing_function` 和 `meta_function` 两个回调，把"怎么爬"和"怎么解析"彻底解耦

### 回调函数设计模式：策略模式（Strategy Pattern）

```
SitemapLoader（框架）
    │
    ├── parsing_function = langchain_docs_extractor  ← 内容策略
    └── meta_function = metadata_extractor           ← 元数据策略
```

这是典型的**策略模式**：框架负责"遍历 URL + 下载 HTML"，策略负责"如何从 HTML 提取有用信息"。
- 好处：换个网站只需换策略函数，SitemapLoader 逻辑不变
- 面试要点：这也是 LangChain 大量使用的模式（BaseLoader 的子类化本质也是策略）

### get_text() 递归生成器

`langchain_docs_extractor` 内部用 **递归生成器（Recursive Generator）** 遍历 DOM 树：

```python
def get_text(tag: Tag) -> Generator[str, None, None]:
    for child in tag.children:
        if isinstance(child, Tag):
            if child.name == "h1":
                yield f"# {child.get_text()}\n\n"
            # ... 其他标签
            else:
                yield from get_text(child)  # 递归
```

- **为什么用生成器而非字符串拼接？** 避免大量中间字符串对象，内存友好
- **yield from** 是 Python 3.3+ 的语法糖，等价于 `for x in get_text(child): yield x`
- 最终 `"".join(get_text(content_soup))` 一次性拼接，效率最优

### 文件保存的路径折叠算法

`save_documents` 中的 `dir_children` 算法解决了一个实际问题：
**URL 路径层级过深时，避免产生大量只有一个子项的嵌套目录**。

思路：从根到叶扫描每一层，找到最深的"有多个分支"的层作为锚点，剩余路径折叠为文件名。

---

## 第 3 层：生产级注意事项

### 关键配置项

| 配置 | 当前值 | 调优建议 |
|------|--------|---------|
| `filter_urls` | 仅 python/langchain/ | 按需扩展（如加 langsmith 文档） |
| `default_parser` | "lxml" | lxml 速度最快，需 pip install lxml |
| `USER_AGENT` | Chrome UA | 部分站点会检查 UA，保持真实浏览器 UA |

### 常见坑点

1. **sitemap.xml 可能很大**：LangChain 全站 sitemap 有数千个 URL，不加 `filter_urls` 会爬很久（30min+）且产生大量文件
2. **网络超时**：SitemapLoader 默认无超时和重试，大规模爬取时偶尔会失败。生产环境应加 `requests_kwargs={"timeout": 30}`
3. **YAML frontmatter 特殊字符**：metadata 值含 `:` `#` `"` 时会破坏 YAML 解析。应使用 `yaml.dump()` 或对值加引号
4. **编码问题**：极少数页面可能有非 UTF-8 字符，`clean_text()` 已处理但要注意
5. **幂等性**：重复运行不会自动清理旧文件，可能产生重复。建议运行前清空输出目录

### 性能与成本

- 爬取是**纯网络 I/O**，不涉及 LLM 调用，零 API 成本
- 爬取一次后数据持久化到本地，后续 Task 不再需要重新爬取
- 建议：将爬取结果纳入 Git（或 .gitignore 但保留索引文件），确保团队成员不必重复爬取

---

## 第 4 层：验收标准与测试要点

### 验收检查项

- [x] `data/langchain_python_separated/` 目录存在且包含 .md 文件
- [x] `metadata_index.json` 存在且为合法 JSON
- [x] 随机抽查 3 个 .md 文件：包含 YAML frontmatter + Markdown 正文
- [x] Markdown 中代码块格式正确（有 ``` 包裹）
- [x] 无空文件（page_content 不为空）

### 验证命令

```bash
# 检查文件数
ls data/langchain_python_separated/oss/python/langchain/ | measure

# 检查 JSON 索引是否合法
python -c "import json; data=json.load(open('data/langchain_python_separated/metadata_index.json','r',encoding='utf-8')); print(f'共 {len(data)} 条索引')"

# 抽查一个文件的前 10 行
head -n 10 data/langchain_python_separated/oss/python/langchain/rag.md
```

### 数据现状

当前 `data/langchain_python_separated/` 已有 34 个文档 + 索引文件，数据已就绪。

---

## 第 5 层：完整代码（最小修正版）

本次仅做两处修正，不做大重构：

1. **拼写修正**：`FLITER_FLAG` → `FILTER_FLAG`
2. **YAML 安全**：`save_documents` 中 frontmatter 值加引号防转义

其余代码保持不变，完整文件见 `src/craw_html_to_md.py`。
