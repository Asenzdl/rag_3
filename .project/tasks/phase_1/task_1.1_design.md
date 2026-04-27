# Task 1.1 切分策略优化与向量库重建 - 实现文档

## 第 1 层：代码骨架

### 目标模块结构

```
src/ingestion/
├── __init__.py              # 公共 API 导出
├── loader.py                # 文档加载 + frontmatter 解析 + metadata 整合
├── splitter.py              # SmartDocumentSplitter + 代码块保护
└── vectorstore.py           # Chroma 入库逻辑

src/load_data.py             # 瘦编排层（仅调用 ingestion 子模块）
```

### 各文件核心签名

**loader.py**: `load_directory()`, `load_metadata_index()`, `enrich_docs_with_index()`
**splitter.py**: `SmartDocumentSplitter` (smart_split, _protect_code_blocks)
**vectorstore.py**: `ingest_to_chroma()`
**load_data.py**: `run_pipeline()` 编排入口

### 模块依赖关系

```
load_data.py (编排层)
    ├── ingestion.loader      # 加载 + metadata
    ├── ingestion.splitter    # 切分
    └── ingestion.vectorstore # 入库
           └── config.ollama_embeddings
```

---

## 第 2 层：架构设计思路

### 为什么要拆分？

原 `load_data.py` 是 432 行的单体文件，混合了四种职责：
1. 文档加载（I/O 操作）
2. Metadata 处理（数据转换）
3. 文档切分（NLP 策略）
4. 向量库写入（存储层）

拆分后每个模块只关注一个维度，符合 **单一职责原则（SRP）**。

### 分层架构（Layered Architecture）

```
load_data.py     ← 编排层（Orchestration）: 控制流程顺序
  ↓
ingestion/       ← 业务层（Business Logic）: 各步骤的实现
  ├── loader     :  数据读取
  ├── splitter   :  数据处理
  └── vectorstore:  数据持久化
```

这个分层与未来 FastAPI 服务化（Phase 5）天然兼容：
- API 层直接导入 `ingestion` 包，不依赖 `load_data.py`
- 可以独立测试每个模块

### SmartDocumentSplitter 的策略模式

切分器内部采用 **两阶段管线（Pipeline）** ：

```
原始 Document
    → MarkdownHeaderTextSplitter  (按 h1/h2 标题切分)
    → _protect_code_blocks()      (代码块边界保护)
    → RecursiveCharacterTextSplitter (超大段递归切分)
    → 带完整 metadata 的 chunks
```

每个阶段独立，可以单独替换或扩展。

### 代码块保护的核心思路

LangChain 文档特征：**文字少、代码多**。直接用 `RecursiveCharacterTextSplitter` 会在代码块中间截断，导致检索到的片段不可读。

保护策略：
1. 正则找出所有 ` ```...``` ` 代码块位置
2. 在代码块**边界之间**的文本处切分（而非代码块内部）
3. 「说明 + 代码块」总长 < chunk_size 时合并为一段
4. 超长代码块保持完整，交给递归切分处理

---

## 第 3 层：生产级注意事项

### 关键配置项

| 配置 | 当前值 | 调优依据 |
|------|--------|---------|
| chunk_size | 2000 | 代码密集文档需要更大 chunk 保完整性 |
| chunk_overlap | 200 | ~10% overlap，平衡上下文连贯与去重 |
| headers_to_split_on | h1/h2 | h3-h5 导致过度碎片化（文档代码多文字少） |

### 常见坑点

1. **MarkdownHeaderTextSplitter 不保留标题行**：切分后标题变成 metadata 而非 page_content，下游 LLM 看不到标题文字。需要在 metadata 中保留 h1/h2 键。
2. **Chroma metadata 类型限制**：只支持 str/int/float/bool，None 和 list 会报错。`ingest_to_chroma` 中必须做类型清洗。
3. **代码块正则的边界情况**：嵌套代码块（` ```` ` 内含 ` ``` `）、未闭合代码块。当前正则 `r'```[\w]*\n[\s\S]*?```'` 用非贪婪匹配，能处理大多数情况。
4. **向量库重建**：重新运行时需确保旧的 persist_directory 被清空，否则 Chroma 会追加而非覆盖。

### 性能与成本

- 切分是纯 CPU 操作，无 API 调用
- 入库时 Ollama embedding 是本地模型，零费用但受 GPU/CPU 性能限制
- 34 篇文档 → ~200-400 个 chunks → embedding 约 1-3 分钟（本地 Ollama）

---

## 第 4 层：验收标准与测试要点

### 验收检查项

- [ ] `src/ingestion/` 目录存在，包含 4 个文件
- [ ] `src/load_data.py` 精简为 < 50 行的编排层
- [ ] `python src/load_data.py` 可正常执行完整 pipeline
- [ ] 随机抽样 chunk，代码块无截断
- [ ] 向量库可正常检索

### 建议的验证方式

```python
# 验证模块可导入
from ingestion import load_directory, SmartDocumentSplitter, ingest_to_chroma

# 验证切分结果
splitter = SmartDocumentSplitter(chunk_size=2000, chunk_overlap=200)
chunks = splitter.smart_split(docs)
# 检查代码块完整性
for c in chunks[:10]:
    opens = c.page_content.count("```")
    assert opens % 2 == 0, f"代码块未闭合: {c.metadata}"
```

---

## 第 5 层：完整代码

本次为纯重构，将 `load_data.py` 拆分为 `src/ingestion/` 包的 3 个模块文件。
函数签名和内部逻辑零修改，仅调整 import 路径。

完整代码见：
- `src/ingestion/__init__.py`
- `src/ingestion/loader.py`
- `src/ingestion/splitter.py`
- `src/ingestion/vectorstore.py`
- `src/load_data.py`（精简版）
