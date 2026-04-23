# Task 1.9 Prompt 接口修复与代码质量改善 - 架构设计

> **原始需求**：`.project_outline/phase_1_reliable_base/task_1.9_prompt_fix_code_quality.md`
> **涉及文件**：`src/generation/prompts.py`、`src/generation/citation_chain.py`、`src/evaluation/dataset.py`、`tests/test_prompts.py`、`tests/test_citation_chain.py`、`tests/test_dataset.py`

---

## 架构决策与权衡

### 决策 1：消息顺序修复范围 — 仅调整 `_build_messages` 内部顺序

- **设计原则**：接口最小变更、行为修正
- **选项 A**：仅将 `MessagesPlaceholder("chat_history")` 移到 `HumanMessagePromptTemplate` 之前 — 优点：改动最小、仅修正 bug、零运行时影响（Phase 1 未启用 include_chat_history）；缺点：无
- **选项 B**：重构 `_build_messages` 为策略模式 — 优点：更灵活；缺点：过度设计，当前仅两种可选插入项
- **结论**：选 A。修复仅影响 `include_chat_history=True` 路径，Phase 1 全部默认 False，零运行时影响。正确顺序：System → [Few-shot] → ChatHistory → Human（当前问题必须在最后，这是 Chat 模型对消息顺序的硬性要求）
- **技术文档展开方向**：讲透 MessagesPlaceholder 的底层机制、消息顺序对模型行为的影响

### 决策 2：`CitationExtractor.extract()` 异常拆分策略

- **设计原则**：鲁棒性、精确异常捕获
- **选项 A**：将 `except (NotImplementedError, Exception)` 拆为三条独立 except — 优点：NotImplementedError 回退正则、CitationExtractionError 向上传播、Exception 防御性兜底；缺点：行为变更（CitationExtractionError 不再回退正则）
- **选项 B**：仅分离 NotImplementedError，其余保持 `except Exception` — 优点：行为变更更小；缺点：仍然过宽捕获，CitationExtractionError 被吞没违背 outline 要求
- **结论**：选 A。`_extract_structured` 内部已将非 `NotImplementedError` 包装为 `CitationExtractionError`（行 370-374），因此 `extract()` 内部的 `except` 需拆为三条。RAGChain 已捕获 `CitationExtractionError` 返回空引用，端到端行为可接受
- **技术文档展开方向**：讲透 Python 异常继承链、精确捕获 vs 过宽捕获的工程权衡

### 决策 3：`dataset.py` 日志替换范围

- **设计原则**：可观测性（结构化日志）
- **选项 A**：仅替换行 71 的 `print(f"[WARN]...")` 为 `logger.warning()` — 优点：最小改动、符合 outline 要求
- **选项 B**：同时替换 `print_dataset_stats()` 中的 print — 缺点：outline 明确标注 `print_dataset_stats` 为 CLI 输出，print 是正确的输出方式
- **结论**：选 A。新增 `import structlog` + `logger = structlog.get_logger(__name__)`，仅替换行 71

---

## 设计约束与假设

### 外部约束
- Phase 1 所有代码路径 `include_chat_history=False`，修复无运行时影响
- `CitationExtractionError` 向上传播后，RAGChain 的 `except CitationExtractionError` 会捕获并返回 `citations=[]` 的 RAGResponse

### 设计假设
- structlog 已被项目广泛使用，无循环导入风险
- `print_dataset_stats()` 的 print 保留是正确的（CLI 输出场景）

### 隐含前提
- 测试文件中两个断言了错误消息顺序的测试（`test_messages_order`、`test_with_chat_history_has_placeholder`）必须同步修改

---

## 模块结构

### 文件组织
```
src/generation/
├── prompts.py          # 修复 chat_history 位置
├── citation_chain.py   # 拆分过宽异常捕获
└── exceptions.py       # 不变（CitationExtractionError 已定义）

src/evaluation/
└── dataset.py          # print→logger.warning

tests/
├── test_prompts.py          # 修改断言 + 新增测试
├── test_citation_chain.py   # 修改断言 + 新增测试
└── test_dataset.py          # 新建
```

### 职责边界
```
prompts.py 职责：
✅ 包含：修复 MessagesPlaceholder 位置、更新 docstring
❌ 不包含：修改 get_prompt() 接口  ← 接口不变

citation_chain.py 职责：
✅ 包含：拆分 extract() 内部 except 块
❌ 不包含：修改 _extract_structured 或 _extract_regex  ← 内部逻辑不变

dataset.py 职责：
✅ 包含：替换 load_eval_dataset 中的 print 为 logger.warning
❌ 不包含：修改 print_dataset_stats  ← CLI 输出保留 print
```

---

## 契约速览

### prompts.py（修改）

```python
def _build_messages(...) -> list:  # P0（已有，修复内部顺序）
    """组装 ChatPromptTemplate 的 messages 列表 — 修复后顺序：System → [Few-shot] → ChatHistory → Human"""
```

### citation_chain.py（修改）

```python
class CitationExtractor:  # P0（已有，修复 extract() 异常处理）
    def extract(self, answer: str, sources: List[str]) -> List[ValidatedCitation]: ...
    # 内部 except 块从 1 条拆为 3 条
```

### dataset.py（修改）

```python
def load_eval_dataset(json_path: str) -> List[EvalSample]:  # P0（已有，替换 print 为 logger.warning）
```

---

## 错误处理策略

### 异常捕获与包装策略（citation_chain.py extract() 方法）

| # | 异常类型 | 捕获位置 | 包装为 | 是否中断主流程 | 理由 |
|---|---------|---------|-------|-------------|------|
| 1 | `NotImplementedError` | `extract()` 内层 try | 无（回退正则） | 否 | 模型不支持 Function Calling，回退正则策略 |
| 2 | `CitationExtractionError` | `extract()` 内层 try | 无（重新抛出） | 是（由外层处理） | `_extract_structured` 已包装的已知异常，应向上传播 |
| 3 | `Exception` | `extract()` 内层 try | 无（回退正则） | 否 | 防御性兜底，未知异常回退正则 |
| 4 | `CitationExtractionError` | `extract()` 外层 try | 无（重新抛出） | 是 | 已知异常直接传播 |
| 5 | `Exception` | `extract()` 外层 try | `CitationExtractionError` | 是 | 未知异常包装后抛出 |

### 可恢复 vs 不可恢复的判定
- **可恢复**（不中断主流程）：NotImplementedError → 回退正则；一般 Exception → 回退正则
- **不可恢复**（中断并上抛）：CitationExtractionError → 向上传播到 RAGChain

---

## 代码骨架

### prompts.py — `_build_messages` 修复

```python
def _build_messages(
    system_template: str,
    human_template: str,
    include_few_shot: bool = False,
    include_chat_history: bool = False,
) -> list:  # P0
    """组装 ChatPromptTemplate 的 messages 列表。

    消息顺序（修复后）：
        1. SystemMessage — 全局行为指令
        2. [Few-shot 示例对] — Human + AI 示例（可选）
        3. [MessagesPlaceholder("chat_history")] — 对话历史（可选，Task 2.5 预留）
        4. HumanMessage — 当前问题 + 上下文（核心交互消息，必须在最后）

    修复原因：
        Chat 模型要求当前 Human 消息在消息列表末尾。
        若 chat_history 在 Human 之后，模型会将历史消息视为当前输入的一部分，
        导致上下文混乱（模型无法区分"历史"和"当前问题"）。

    Args:
        ...（同现有）
    """
    # 步骤 1：System Message — 全局行为指令（不变）
    # 步骤 2：Few-shot 示例（可选，不变）
    # 步骤 3：Chat history 占位符（可选）— 从原第4步移至此处
    #   条件：include_chat_history 为 True
    #   动作：追加 MessagesPlaceholder("chat_history")
    #   为什么移到 Human 之前：对话历史必须在当前问题之前，
    #   模型需要先看到历史再回答当前问题
    # 步骤 4：Human Message — 当前问题 + 上下文 — 从原第3步移至此处
    #   这是核心交互消息，必须在 messages 列表末尾
```

### citation_chain.py — `extract()` 异常拆分

```python
def extract(self, answer: str, sources: List[str]) -> List[ValidatedCitation]:  # P0
    """从回答文本中提取引用并验证。（docstring 不变）"""
    # 步骤 1：边界处理 — answer 为空 → 返回空列表（不变）
    # 步骤 2：根据策略选择提取方法
    #   步骤 2a：if self._use_structured_output:
    #     try:
    #       调用 self._extract_structured(answer, sources)
    #       日志：info 记录 citation_count、valid_count
    #       return citations
    #     except NotImplementedError:            # 按异常策略表第 1 行处理
    #       日志：warning "模型不支持 Function Calling，回退到正则策略"
    #     except CitationExtractionError:        # 按异常策略表第 2 行处理
    #       raise  # 向上传播，不回退正则
    #     except Exception as e:                 # 按异常策略表第 3 行处理
    #       日志：warning 记录 error、error_type，回退正则
    #   步骤 2b：正则策略（默认或回退）（不变）
    # 步骤 3：外层异常处理（不变）
    #   except CitationExtractionError: raise    # 按异常策略表第 4 行
    #   except Exception as e: 包装为 CitationExtractionError  # 按异常策略表第 5 行
```

### dataset.py — 日志替换

```python
# 新增（在现有 import 之后）：
# import structlog
# logger = structlog.get_logger(__name__)

def load_eval_dataset(json_path: str = "data/eval/qa_pairs.json") -> List[EvalSample]:  # P0
    """加载评估数据集。（docstring 基本不变）"""
    # ...（前面不变）
    # 步骤 N：except KeyError as e:
    #   将 print(f"[WARN] 跳过第 {i} 条数据，缺少字段: {e}")
    #   替换为 logger.warning("跳过数据，缺少字段", index=i, missing_field=str(e))
    # ...（后面不变）
```

---

## 常见坑点

1. **消息顺序混淆**：容易将 chat_history 放在 Human 之后，因为"追加到末尾"是直觉操作。Chat 模型的 attention 机制对末尾 token 权重更高，当前问题必须在最后，否则模型会混淆历史和当前输入。
2. **except 顺序错误**：Python except 块按顺序匹配，`except Exception` 必须放在最后。若 `except CitationExtractionError` 放在 `except Exception` 之后，将永远不会被触发（因为 CitationExtractionError 是 Exception 的子类）。
3. **测试同步遗漏**：修改消息顺序后，`test_messages_order` 和 `test_with_chat_history_has_placeholder` 的断言必须同步修改，否则测试会误报"修复失败"。

---

## 测试策略概要

### Mock 边界
- `test_citation_chain.py`：Mock LLM（`MagicMock`）模拟 with_structured_output 行为
- `test_dataset.py`：Mock `structlog.get_logger` 捕获 warning 调用；临时 JSON 文件用 `tmp_path` fixture

### 可独立测试的纯函数
- `_build_messages`：无副作用，直接断言返回列表元素类型和顺序
- `load_eval_dataset`：纯文件 I/O + 数据转换

### 关键测试场景
- chat_history 在 HumanMessagePromptTemplate 之前（索引比较）
- CitationExtractionError 从 _extract_structured 传播到 extract() 外层
- dataset.py 缺少字段时 logger.warning 被调用

---

## 验收标准

### 功能验收
- [ ] `get_prompt(include_chat_history=True).invoke({"context": "...", "question": "...", "chat_history": []})` 正常工作
- [ ] 消息顺序：System → [Few-shot] → MessagesPlaceholder → HumanMessagePromptTemplate
- [ ] `CitationExtractionError` 从 `_extract_structured` 传播到 `extract()` 外层
- [ ] `dataset.py` 缺少字段时使用 `logger.warning()` 而非 `print`

### 质量验收
- [ ] 全量测试通过
- [ ] `print_dataset_stats()` 中的 print 保留不变

### 性能验收
- [ ] 无性能影响（纯接口修复 + 代码质量改善）

---

## 最佳实践自检清单

### 关键落地点

- **鲁棒性/容错**：citation_chain.py 异常捕获从过宽 `except (NotImplementedError, Exception)` 拆分为三条精确 except 块，CitationExtractionError 正确传播
- **可观测性**：dataset.py 的 `print(f"[WARN]...")` 替换为结构化 `logger.warning()`，包含 index、missing_field 上下文字段
- **可测试性**：新增 4 个测试覆盖消息顺序、异常传播、日志调用场景

### 常规落地

- [x] 模块分离：文件职责边界已在"职责边界"章节说明
- [x] 架构分层：数据流和层次关系已在"架构决策"和"模块结构"中体现
- [x] SOLID 原则：接口不变（开闭原则），仅修复内部实现
- [x] 封装与抽象：公共 API 无变更
- [x] 设计模式：当前修复不需要新设计模式
- [x] 可观测性：P0 函数已标注日志记录点
- [x] 配置管理：无新增配置项
- [x] 鲁棒性/容错：异常体系已在"错误处理策略"中集中描述
- [x] 可测试性：依赖注入点已在骨架中标注
- [x] 可扩展性：修复后的消息顺序为 Task 2.5 记忆模块提供正确接口

### 豁免声明

- 设计模式维度：本 Task 是 bug 修复 + 代码质量改善，不引入新的设计模式，不适用

---

## 前瞻性设计（精简）

### 与后续 Task 的接口衔接
- Task 2.5：修复后的 `_build_messages` 函数将作为对话记忆的 Prompt 注入接口，Phase 2 将 `state["messages"]` 经裁剪后作为 `chat_history` 传入
