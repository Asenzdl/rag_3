# Task 1.2 评估数据集构建 - 实现文档

## 第 1 层：代码骨架

### 模块结构

```
data/eval/qa_pairs.json          # 26 个 QA pairs (补充 id + 细化 category)
src/evaluation/
├── __init__.py                  # 公共导出
├── dataset.py                   # EvalSample + load_eval_dataset + print_dataset_stats
└── retrieval_eval.py            # (后续 Task 1.4)
```

### 核心签名

```python
@dataclass
class EvalSample:
    id: str                              # "q001" ~ "q026"
    question: str                        # 中文问题
    expected_sources: List[str]          # 预期 source URL
    category: str                        # rag/agents/memory/tools/graph-api/...
    difficulty: str                      # easy/medium/hard
    relevant_doc_ids: Optional[List[str]] = None  # chunk 级（可选）

def load_eval_dataset(json_path: str = "data/eval/qa_pairs.json") -> List[EvalSample]: ...
def print_dataset_stats(samples: List[EvalSample]) -> None: ...
```

---

## 第 2 层：架构设计思路

### 为什么用 dataclass 而不是 dict？

- **类型安全**：IDE 自动补全、静态检查
- **自文档化**：字段名 + 类型注解 = 无需额外文档
- **不可变性友好**：可加 `frozen=True` 防止意外修改
- **面试要点**：Python 3.7+ 的 `@dataclass` 是值对象（Value Object）的标准实现

### Golden Dataset 的设计原则

1. **多样性**：12 个分类覆盖 LangChain + LangGraph 核心能力
2. **难度分层**：easy/medium/hard 约 2:4:3，评估不同检索难度
3. **来源可追溯**：每个 QA 标注了 expected_sources（真实 URL）
4. **可扩展**：JSON 格式 + 可选字段（relevant_doc_ids），后续可逐步补充 chunk 级标注

### 与下游模块的交互

```
dataset.py → EvalSample 列表
    ↓
retrieval_eval.py (Task 1.4)  → 拿 question 检索，对比 expected_sources
    ↓
rag_chain_eval (Task 1.6+)    → 拿 question 生成回答，评估质量
```

---

## 第 3 层：生产级注意事项

### 数据集维护

- **版本控制**：`qa_pairs.json` 必须纳入 Git，每次修改说明原因
- **数据量**：26 条对于开发迭代够用，生产级建议 100+
- **标注质量**：expected_sources 必须指向真实存在的文档 URL，否则评估结果无意义

### 常见坑点

1. **相对路径**：`load_eval_dataset()` 默认路径 `data/eval/qa_pairs.json` 依赖 CWD。从项目根运行没问题，从 `src/` 运行会找不到。生产环境应改为绝对路径或配置项。
2. **JSON 编码**：中文问题必须 `ensure_ascii=False` 保存，UTF-8 编码读取。
3. **id 唯一性**：当前 id 为手动编号，扩展时需确保不重复。

---

## 第 4 层：验收标准

- [x] `qa_pairs.json` 包含 26 个 QA pairs，每条有 id/question/expected_sources/category/difficulty
- [x] 12 个分类覆盖 rag/agents/memory/tools/graph-api 等
- [x] `load_eval_dataset()` 正确加载并返回 `List[EvalSample]`
- [x] `print_dataset_stats()` 输出统计信息：总数 26，难度分布 easy 6/medium 11/hard 9
- [x] 24 个去重 source URL 均指向真实 LangChain 文档

---

## 第 5 层：完整代码

代码见：
- `data/eval/qa_pairs.json` — 26 条 QA pairs（补充 id + 细化 category）
- `src/evaluation/dataset.py` — EvalSample dataclass + 加载器 + 统计
- `src/evaluation/__init__.py` — 公共导出
