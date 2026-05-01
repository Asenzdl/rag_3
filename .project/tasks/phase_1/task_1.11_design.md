# Task 1.11 RAGChain 方法拆分与代码质量改善 - 架构设计

> **原始需求**：`.project/outline/phase_1_reliable_base/task_1.11_rag_chain_refactor_code_quality.md`
> **涉及文件**：`src/generation/rag_chain.py`、`src/generation/citation_chain.py`、`src/evaluation/dataset.py`

---

## 架构决策与权衡

### 先读：这不是填空题

本 Task 的核心动作是"拆分 God Method"，但拆分的粒度、异常边界的划分、返回类型的设计，都有实质性的结构影响。以下两个决策直接影响调用链和步骤方法签名。

---

### 入口判定

1. **异常边界**：若步骤方法内部包装所有异常，编排层无需 try/except → invoke() 变成纯顺序调用；若步骤方法保留原始异常，编排层需显式 catch → invoke() 含异常分支。两种方案调用链结构不同。**命中**。
2. **_generate_step 返回类型**：若返回 `str`，token usage 在步骤内部日志；若返回 `tuple[str, dict]`，编排层持有 token 数据可做后续处理（如写入 Prometheus）。两种方案返回类型不同，且影响 Task 4.6 的实现路径。**命中**。

---

### 决策 1：步骤方法异常边界 — 保留原始异常 vs 步骤内包装

**语境**：`_retrieve_step()` 被 `invoke()`、`retrieve()`、`stream()` 三个调用方共享。三个调用方对 `RetrievalError` 的处理策略不同：`invoke()` 包装为 `GenerationError`，`retrieve()` 也包装为 `GenerationError`，`stream()` yield 错误提示文本。如果步骤方法内部包装了异常，调用方就无法区分异常来源做差异化处理。

**候选对比**：

- **方案 A**：所有步骤方法保留原始异常（`RetrievalError`、SDK 原始异常），编排层统一包装
  - 在本项目语境下的优势：调用方有完整上下文做差异化处理（`stream()` 需要 yield 而非 raise）
  - 在本项目语境下的硬伤：`_generate_step()` 需要保留 SDK 原始异常（如 `openai.APIError`），编排层需理解每种底层异常如何包装为 `LLMCallError`（需判断 `is_retryable`），违反 SRP——编排层不应承担 LLM 异常分类的职责

- **方案 B**：检索步骤保留原始异常，生成/引用步骤内部包装为业务异常
  - 在本项目语境下的优势：`_generate_step()` 内部有足够上下文判断 `is_retryable`（重试耗尽 → False，网络超时 → True）；`_extract_citations_step()` 内部处理非致命异常（返回空列表）；编排层只需处理 `RetrievalError` 的包装
  - 在本项目语境下的硬伤：异常处理策略分散在步骤方法和编排层两处，读者需在两处理解异常处理逻辑

**反驳推演**：如果选方案 A，`invoke()` 需要这样处理 LLM 异常：`except openai.APITimeoutError → LLMCallError(is_retryable=True)`、`except openai.AuthenticationError → LLMCallError(is_retryable=False)`、`except Exception → LLMCallError(is_retryable=False)`。这些判断逻辑本属于 LLM 调用层，外溢到编排层后，切换 LLM 提供商（DeepSeek → Qwen）时需同时修改编排层和步骤方法两处代码。

**结论**：选 B，根本理由是 `_generate_step()` 内部拥有判断 `is_retryable` 的完整上下文（重试装饰器的重试耗尽状态、SDK 异常类型），编排层不应承担这个职责。如果 LLM 异常分类逻辑变得更复杂（如增加区分 Rate Limit 和 Server Error），方案 A 的编排层会持续膨胀。

**反事实自检**：

- [x] 方案 A 不再失效（如果 LLM 异常只有一种类型且无需 `is_retryable` 判断），两方案都可行 → "LLMCallError 需携带 `is_retryable` 语义"正是让方案 A 失效的原因 → 验证通过

---

### 决策 2：_generate_step 返回类型 — 单一值 vs 复合结构

**语境**：`_generate_step()` 内部调用 `_retryable_invoke()` 获得 `AIMessage`，从中提取 answer 文本和 token usage。当前 `invoke()` 将 token usage 记录在"生成完成"日志中，无其他消费方。Task 4.6（Prometheus 监控）可能需要 token usage 数据作为指标。

**候选对比**：

- **方案 A**：返回 `str`（仅 answer），token usage 在步骤内部日志记录
  - 在本项目语境下的优势：简单，步骤方法自治（自己负责可观测性）；符合"禁止超前实现"原则
  - 在本项目语境下的硬伤：Task 4.6 若需暴露 token usage 给 Prometheus 指标，需修改返回类型

- **方案 B**：返回 `tuple[str, TokenUsage]`（answer + token 数据），编排层决定如何使用
  - 在本项目语境下的优势：编排层拥有完整数据，可灵活路由到日志/Prometheus/计费系统
  - 在本项目语境下的硬伤：引入复合返回类型，当前唯一消费方（invoke）只需 answer，token 数据被解构后立即丢弃；且需定义 `TokenUsage` 数据结构（当前为 3 个 int 字段，定义专门 dataclass 是过度设计）

**反驳推演**：如果选方案 B，`invoke()` 需要 `answer, usage = self._generate_step(...)` 解构，但 `usage` 仅用于日志——而 `_generate_step()` 内部已经记录了相同日志。`invoke()` 持有 `usage` 后无实际用途，属于"数据流经但未消费"的冗余路径。

**结论**：选 A，根本理由是 CLAUDE.md 的"禁止超前实现"原则——当前无消费方需要 token usage 数据，提前暴露是 YAGNI 违规。如果 Task 4.6 需要向 Prometheus 推送 token 指标，结论会反转（需要返回复合结构或引入指标回调）。

**反事实自检**：

- [x] 方案 B 不再失效（如果 Task 4.6 需要暴露 token usage 给 Prometheus），两方案都可行 → "当前无消费方需要 token usage"正是让方案 B 失效的原因 → 验证通过

---

### 质量准则豁免

无。10 维最佳实践在本 Task 中均有落地方式。

---

## 模块结构

### 文件组织
```
src/generation/
├── __init__.py          # 公共导出（不变）
├── rag_chain.py         # RAGChain 方法拆分 + ainvoke 修复
├── citation_chain.py    # 代码质量改善
├── prompts.py           # 不变
└── exceptions.py        # 不变

src/evaluation/
├── dataset.py           # 使用 settings.eval_qa_path 替代硬编码路径
```

### 关键外部依赖
```
rag_chain.py
├── time                 # perf_counter 计时
├── structlog            # 结构化日志
├── langchain_core       # Document, BaseChatModel, StrOutputParser, ChatPromptTemplate
├── src.generation.citation_chain   # CitationExtractor, ValidatedCitation
├── src.generation.exceptions       # CitationExtractionError, EmptyRetrievalError, GenerationError, LLMCallError
├── src.retriever.base_retriever    # RetrievalError
├── src.retriever.protocols         # RetrieverProtocol
└── src.utils.retry                 # with_retry

dataset.py
├── src.core.config      # settings（延迟导入，仅默认参数解析时使用）
```

### 职责边界
```
rag_chain.py 重构后职责：
✅ 包含：RAGChain 编排方法（invoke/stream/retrieve/extract_citations/ainvoke）
✅ 包含：私有步骤方法（_retrieve_step/_generate_step/_extract_citations_step）
✅ 包含：format_docs 独立函数
✅ 包含：RAGResponse 数据结构
❌ 不包含：检索器/LLM/Prompt 的创建逻辑 ← 属于 factories.py
❌ 不包含：引用提取策略实现 ← 属于 citation_chain.py

新增私有步骤方法职责：
_retrieve_step(question) → List[Document]
  ✅ 包含：调用检索器、计时、日志
  ❌ 不包含：异常包装（保留 RetrievalError）、空检索拦截（编排层职责）

_generate_step(context, question) → str
  ✅ 包含：带重试 LLM 调用、token 追踪、异常包装为 LLMCallError、计时、日志
  ❌ 不包含：流式生成（stream 独立实现）

_extract_citations_step(answer, sources) → List[ValidatedCitation]
  ✅ 包含：调用引用提取器、非致命异常降级为空列表、计时、日志
  ❌ 不包含：引用验证策略 ← 属于 CitationExtractor
```

### 与后续 Task 的接口衔接
- Task 2.2：LangGraph 检索节点直接调用 `create_retriever(settings)`，不经过 `_retrieve_step()`
- Task 2.7：CLI 升级后 `RAGChain` 类可逐步废弃
- Task 4.5：`ainvoke()` 占位处实现完整异步链路
- Task 4.6：若需 Prometheus 指标，`_generate_step()` 返回类型可能需调整（见决策 2 反转条件）

---

## 错误处理策略

| 异常类型 | 产生位置 | 步骤方法行为 | 编排层处理 | 是否中断主流程 | 理由 |
|---------|---------|------------|-----------|-------------|------|
| `RetrievalError` | `_retrieve_step()` | 保留原始异常向上传播 | `invoke()`/`retrieve()` 包装为 `GenerationError`；`stream()` yield 错误提示 | 是（invoke/retrieve）| 统一在编排层转换，步骤方法无上下文判断应包装为何种异常 |
| SDK 原始异常 | `_generate_step()` | 内部包装为 `LLMCallError(is_retryable=False)` | 不处理，`LLMCallError` 是 `GenerationError` 子类，自然传播 | 是 | 步骤方法有重试耗尽上下文，可准确判断 `is_retryable` |
| `CitationExtractionError` | `_extract_citations_step()` | 内部捕获，降级为空列表 | 不处理 | 否 | 引用提取是增强功能，不应中断主流程 |

---

## 测试策略概要

### Mock 边界
- `_retryable_invoke`：继续 mock 为返回 AIMessage，与现有测试兼容
- `_retriever`：继续 mock 为返回 `List[Document]`
- `_citation_extractor`：继续 mock 为返回 `List[ValidatedCitation]` 或抛 `CitationExtractionError`

### 可独立测试的函数/方法
- `format_docs()`：纯函数，已有测试覆盖
- `_retrieve_step()`：通过 `invoke()`/`retrieve()`/`stream()` 间接测试
- `_generate_step()`：通过 `invoke()` 间接测试
- `_extract_citations_step()`：通过 `invoke()` 间接测试

### 必须覆盖的关键测试场景
- `ainvoke()` 抛出 `NotImplementedError`（替换原假异步测试）
- `invoke()` 正常路径行为不变（回归测试）
- `invoke()` 检索失败时 `RetrievalError` → `GenerationError` 转换（回归测试）
- `stream()` 检索失败时 yield 错误提示（回归测试）
- `retrieve()` 使用 `_retrieve_step()` 的异常路径（回归测试）

---

## 代码蓝图：施工图纸级别

> **`__init__.py`**：无新增公共 API，无需更新导出。

### RAGChain 类 — 新增私有步骤方法

```python
def _retrieve_step(self, question: str) -> List[Document]:
    """共享检索步骤 — 被 invoke/retrieve/stream 复用。

    为什么是私有方法而非独立函数（设计决策）：
        1. 步骤函数仅在 RAGChain 内部使用，Phase 2 LangGraph 节点直接调用底层组件，不复用此方法
        2. 私有方法保持类的内聚性——步骤访问 self._retriever 实例属性，拆为独立函数需传参
        3. format_docs() 是独立函数而非私有方法，因为 Phase 2 生成节点需跨模块复用

    为什么保留 RetrievalError 而不包装（反直觉辩护）：
        三个调用方对检索异常的处理策略不同：
        invoke() → 包装为 GenerationError
        retrieve() → 包装为 GenerationError
        stream() → yield 错误提示文本
        步骤方法若内部包装，调用方无法做差异化处理。

    注意点：此方法不包含空检索拦截逻辑——空检索是编排层决策（是否 raise_on_empty），
    不是检索步骤的职责。

    Args:
        question: 用户问题

    Returns:
        检索到的文档列表

    Raises:
        RetrievalError: 检索过程中发生异常（保留原始语义，由调用方决定包装方式）
    """
    # 步骤 1：计时开始
    # 步骤 2：调用检索器
    #   self._retriever.invoke(question) → docs
    #   注入：self._retriever（可 Mock）
    # 步骤 3：计时结束，计算 latency_ms
    # 步骤 4：日志：info 记录 question(截断50)、doc_count、latency_ms
    # 步骤 5：返回 docs
    # 鲁棒性：RetrievalError 保留原始语义向上传播，由调用方决定包装方式
```

```python
def _generate_step(self, context: str, question: str) -> str:
    """LLM 生成步骤 — 带重试调用 + token 追踪 + 异常包装。

    为什么返回 str 而非 tuple[str, dict]（功能取舍）：
        当前 token usage 仅用于日志，步骤方法内部记录即可。
        若 Task 4.6 需暴露 token 数据给 Prometheus，届时再调整返回类型。
        禁止超前实现——当前无消费方需要 token usage 数据。

    为什么步骤内包装为 LLMCallError 而非保留原始异常（设计决策）：
        LLMCallError 的 is_retryable 属性需要重试耗尽的上下文来判断，
        编排层不具备此上下文。若由编排层包装，需理解每种 SDK 异常类型，
        切换 LLM 提供商时需同时修改编排层。

    为什么 stream() 不复用此方法（替代方案排除）：
        stream() 使用 _generation_chain.stream() 逐 token yield，
        语义完全不同（yield vs return），强行共享需引入回调或生成器协议，
        复杂度远超收益。

    Args:
        context: 格式化后的文档上下文字符串
        question: 用户问题

    Returns:
        LLM 生成的回答文本

    Raises:
        LLMCallError: LLM 调用失败时（重试耗尽后包装为 is_retryable=False）
    """
    # 步骤 1：计时开始
    # 步骤 2：带重试的 LLM 调用
    #   try: self._retryable_invoke({"context": context, "question": question}) → ai_message
    #     注入：self._retryable_invoke（可 Mock，替换为返回 AIMessage 的函数）
    #   except Exception as e:
    #     步骤 2a：计时结束
    #     步骤 2b：日志：error 记录 question(截断50)、error、error_type、latency_ms
    #     步骤 2c：抛出 LLMCallError(message, original_error=e, is_retryable=False)
    #       is_retryable=False：重试耗尽后不再可重试
    # 步骤 3：计时结束，计算 latency_ms
    # 步骤 4：提取 token 使用量
    #   getattr(ai_message, "usage_metadata", None) or {}
    #   → input_tokens / output_tokens / total_tokens
    # 步骤 5：提取回答文本：answer = ai_message.content
    # 步骤 6：日志：info 记录 question(截断50)、answer_length、latency_ms、
    #   input_tokens、output_tokens、total_tokens
    # 步骤 7：返回 answer
    # 鲁棒性：SDK 异常包装为 LLMCallError，is_retryable 由重试耗尽上下文决定
    # 可观测性：日志记录生成耗时和 token 使用量
```

```python
def _extract_citations_step(
    self, answer: str, sources: List[str]
) -> List[ValidatedCitation]:
    """引用提取步骤 — 非致命异常降级为空列表。

    为什么返回空列表而非抛异常（反直觉辩护）：
        引用提取是增强功能，回答文本本身仍然有效。
        调用方（CLI/FastAPI）更关心回答内容，引用缺失不应导致整个请求失败。

    Args:
        answer: LLM 生成的回答文本
        sources: 检索命中的文档 source URL 列表

    Returns:
        验证后的引用列表。提取失败返回空列表。
    """
    # 步骤 1：计时开始
    # 步骤 2：调用引用提取器
    #   try: self._citation_extractor.extract(answer, sources) → citations
    #     注入：self._citation_extractor（可 Mock）
    #   except CitationExtractionError as e:
    #     步骤 2a：日志：warning 记录 error、answer(截断50)
    #     步骤 2b：返回空列表 []
    # 步骤 3：计时结束，计算 latency_ms
    # 步骤 4：日志：info 记录 citation_count、valid_count、latency_ms
    # 步骤 5：返回 citations
    # 鲁棒性：CitationExtractionError 降级为空列表，不中断主流程
```

### RAGChain 类 — 修改的公共方法

```python
def invoke(self, question: str) -> RAGResponse:
    """同步调用完整 RAG 管道（编排方法）。

    编排流程：检索 → 空检索拦截 → 格式化文档 → LLM 生成 → 引用提取 → 封装返回。
    每个步骤的实现细节封装在私有方法中，invoke() 仅负责调用和组装结果。

    为什么逻辑应不超过 30 行（设计决策）：
        God Method 反模式的核心问题是"一个方法承担多个职责"。
        拆分后 invoke() 只负责编排（调用步骤 + 组装结果），
        每个步骤的实现细节封装在私有方法中。
        30 行指纯编排逻辑（不含 docstring/注释），超过 30 行通常意味着
        混入了步骤实现细节。

    Args:
        question: 用户问题（中文）

    Returns:
        RAGResponse 包含回答、来源、引用验证结果

    Raises:
        LLMCallError: LLM 调用失败时
        EmptyRetrievalError: raise_on_empty=True 且检索为空时
        GenerationError: 检索阶段失败时
    """
    # 步骤 1：计时开始（total_start）
    # 步骤 2：检索
    #   try: docs = self._retrieve_step(question)
    #   except RetrievalError as e: 抛出 GenerationError(f"检索阶段失败...") from e
    #   鲁棒性：RetrievalError 在编排层统一转换为 GenerationError
    # 步骤 3：空检索拦截
    #   ├─ docs 为空 + raise_on_empty=True → 抛出 EmptyRetrievalError
    #   └─ docs 为空 + raise_on_empty=False → 返回预设回复 RAGResponse
    #   日志：warning 记录 question(截断50)、raise_on_empty
    # 步骤 4：格式化上下文 + 提取来源
    #   context = format_docs(docs)
    #   sources = [doc.metadata.get("source", "") for doc in docs]（数据变换 → 写表达式）
    # 步骤 5：生成
    #   answer = self._generate_step(context, question)
    #   LLMCallError 自然传播（已是 GenerationError 子类）
    # 步骤 6：引用提取
    #   citations = self._extract_citations_step(answer, sources)
    # 步骤 7：计时结束（total_ms）
    # 步骤 8：日志：info 记录 question(截断50)、retrieval_count、
    #   citation_count、valid_citation_count、total_latency_ms
    # 步骤 9：返回 RAGResponse(answer, sources, citations, retrieval_count=len(docs))
```

```python
def stream(self, question: str) -> Iterator[str]:
    """流式生成：逐 token 返回文本流。

    流式 vs 同步的区别：
        invoke() → 等待全文本生成完毕 → 返回完整 RAGResponse
        stream() → 逐 token 推送 → 调用方实时展示

    为什么流式不包含引用提取：
        引用提取需要完整文本才能执行（正则匹配需看全文），
        流式场景下文本是逐 token 产生的，无法提前提取引用。
        调用方可在流结束后调用 self.extract_citations() 获取引用。

    为什么复用 _retrieve_step 但生成步骤独立实现：
        _retrieve_step 无副作用（纯查询），可安全复用。
        生成步骤语义不同（yield vs return），强行共享需引入回调，
        复杂度远超收益。

    Args:
        question: 用户问题

    Yields:
        str: 逐 token 的文本片段
    """
    # 步骤 1：检索 — 复用共享步骤方法
    #   try: docs = self._retrieve_step(question)
    #   except RetrievalError as e:
    #     日志：error 记录 question(截断50)、error
    #     yield "[检索失败，请稍后重试]"
    #     return
    # 步骤 2：空检索拦截
    #   if not docs:
    #     日志：warning 记录 question(截断50)
    #     yield self._empty_retrieval_response
    #     return
    # 步骤 3：格式化上下文
    #   context = format_docs(docs)
    # 步骤 4：流式生成 — 独立实现
    #   日志：info 记录"开始流式生成"
    #   try: 遍历 self._generation_chain.stream({"context": context, "question": question})
    #     逐 chunk yield
    #   except Exception as e:
    #     日志：error 记录 question(截断50)、error
    #     yield "\n\n[生成失败，请重试]"
    # 鲁棒性：检索失败和生成失败都降级为错误提示文本，不中断流式输出
```

```python
async def ainvoke(self, question: str) -> RAGResponse:
    """异步调用完整 RAG 管道（占位，Task 4.5 应独立评估）。

    为什么用 NotImplementedError 而非假异步（反直觉辩护）：
        async def 中调用同步阻塞函数会阻塞事件循环，导致所有协程挂起。
        这比 NotImplementedError 更危险，因为调用方无法从类型签名判断行为是否真正异步。
        NotImplementedError 诚实告知"此功能未实现"，避免假异步的隐蔽风险。

    当前为占位，后续 Task 4.5 应独立评估异步链路实现。
    """
    # 步骤 1：抛出 NotImplementedError
    #   消息："ainvoke 尚未实现。当前为占位，Task 4.5 应独立评估异步链路实现。"
```

```python
def retrieve(self, question: str) -> List[Document]:
    """仅执行检索步骤，返回文档列表。

    为什么暴露此方法：
        Task 2.2 的 LangGraph 检索节点只需检索，不需走完整 RAG 管道。
        暴露 retrieve 方法避免 LangGraph 重新实例化检索器。

    为什么改用 _retrieve_step()（设计决策）：
        消除 retrieve() 和 invoke() 中的检索异常处理逻辑重复。
        两者都调用 _retrieve_step()，都在编排层捕获 RetrievalError → GenerationError。

    Args:
        question: 用户问题

    Returns:
        检索到的文档列表

    Raises:
        GenerationError: 检索失败时（包装 RetrievalError）
    """
    # 步骤 1：try: 返回 self._retrieve_step(question)
    #   except RetrievalError as e: 抛出 GenerationError(f"检索失败...") from e
    # 鲁棒性：与 invoke() 统一异常包装策略
```

### citation_chain.py — 代码质量改善

```python
def extract(self, answer: str, sources: List[str]) -> List[ValidatedCitation]:
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
    # 步骤 1：边界处理 — answer 为空或纯空白 → 返回 []
    # 步骤 2：计时开始
    # 步骤 3：根据策略选择提取方法
    #   try:
    #     if self._use_structured_output:
    #       步骤 3a：尝试结构化输出策略
    #         try: citations = self._extract_structured(answer, sources)
    #         except CitationExtractionError: 向上传播（已包装的已知异常）
    #         except NotImplementedError: 日志 warning → 回退正则
    #         except Exception as e: 日志 warning → 回退正则
    #         else:
    #           计时结束
    #           日志：info 记录 citation_count、valid_count、latency_ms、策略=结构化输出
    #           返回 citations
    #       步骤 3b：正则策略（默认或回退）
    #         citations = self._extract_regex(answer, sources)
    #         计时结束
    #         日志：info 记录 citation_count、valid_count、latency_ms、策略=正则
    #         返回 citations
    #   except CitationExtractionError: 已知异常，向上传播
    #   except Exception as e: 未知异常 → 包装为 CitationExtractionError 并抛出
    #
    # 改善点（对比重构前）：
    #   1. 结构化输出路径使用 try/except/else，消除原代码中
    #      _extract_structured 成功后的 return 与外层 return 的冗余
    #   2. 新增计时日志，与 rag_chain.py 步骤方法的可观测性风格一致
```

### dataset.py — 代码质量改善

```python
def load_eval_dataset(
    json_path: Optional[str] = None,
) -> List[EvalSample]:
    """加载评估数据集，返回标准化的 EvalSample 列表。

    为什么用延迟导入而非模块级导入（反直觉辩护）：
        evaluation 包声明为离线工具，通常不应依赖 core.config。
        延迟导入将依赖限制在"未指定路径时"的分支内，
        显式传参的调用方无需触发 core.config 的导入。

    Args:
        json_path: QA pairs JSON 文件路径。默认为 None，
            此时从 settings.eval_qa_path 读取。

    Returns:
        EvalSample 列表。

    Raises:
        FileNotFoundError: JSON 文件不存在时抛出。
        KeyError: JSON 条目缺少必要字段时抛出。
    """
    # 步骤 1：若 json_path 为 None → 延迟导入 settings
    #   from src.core.config import settings
    #   json_path = settings.eval_qa_path
    #   为什么延迟导入：避免 evaluation 包对 core.config 的硬依赖
    # 步骤 2：后续逻辑不变（Path 构造、JSON 加载、EvalSample 构建）
```

---

## 常见坑点

1. **假异步的隐蔽性**：`async def ainvoke()` 调用 `self.invoke()` 不会产生任何语法警告或运行时错误，但在 asyncio 事件循环中会阻塞所有协程。类型签名 `async def` 暗示"非阻塞"，调用方（如 FastAPI 路由）会将其安排在事件循环中，导致整个服务卡死。`NotImplementedError` 虽然不够优雅，但至少诚实——调用方会立即知道此方法不可用，而非在运行时发现服务假死。

2. **私有方法过度拆分**：如果将空检索拦截也提取为 `_check_empty_retrieval_step()`，看似"每个步骤都是方法"，但空检索拦截是纯编排逻辑（根据 `raise_on_empty` 决定抛异常还是返回预设回复），且仅在 `invoke()` 中使用，不与 `retrieve()`/`stream()` 共享。提取为方法反而增加间接层，降低可读性。判断标准：**步骤方法应至少被两个调用方复用，或包含非平凡的异常处理/计时/日志逻辑**。

3. **_generate_step 与 stream 的生成步骤不能共享**：`_generate_step()` 使用 `_retryable_invoke()` 返回完整 `AIMessage`，而 `stream()` 使用 `_generation_chain.stream()` 逐 token yield。两者从 LCEL 链的不同位置调用（prompt|llm vs prompt|llm|StrOutputParser），且流式场景下重试语义不同（部分输出已 yield 无法回滚）。强行共享需引入生成器协议或回调，复杂度远超收益。

4. **dataset.py 延迟导入的时序**：`from src.core.config import settings` 在函数内部执行时，`load_dotenv()` 必须已执行。由于 `dataset.py` 的调用方（如 `retrieval_eval.py`）总是在 `config.py` 导入后才使用，时序有保障。但如果有人在 `config.py` 导入前调用 `load_eval_dataset()`（不传参），会拿到未初始化的 settings。防御措施：在 docstring 中注明"默认路径依赖 settings，需确保 config.py 已导入"。
