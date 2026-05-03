# Task 2.2 核心节点函数实现 - 架构设计

> **原始需求**：`.project/outline/phase_2_langgraph/task_2.2_nodes.md`
> **涉及文件**：`src/workflow/nodes.py`、`src/workflow/routing.py`、`src/workflow/__init__.py`、`tests/test_workflow_nodes.py`

---

## 架构决策与权衡

### 先读：这不是填空题

节点函数看似简单（三个 `state -> dict` 函数），但**依赖注入方式**决定了 Task 2.3 的图构建入口签名，**检索失败的错误传播方式**决定了图的执行路径和状态语义。选错依赖注入模式，测试时无法 Mock；选错错误传播方式，route_decision 的语义会被下游节点污染。

---

### 入口判定

1. **节点依赖注入方式**：LangGraph 节点签名固定 `state -> dict`，但节点需要 retriever/llm/prompt 等外部依赖。工厂闭包 vs 模块级导入 vs 类实例——换方案会改变模块边界（nodes.py 是否依赖 config）和调用链（Task 2.3 如何获取节点函数）。**命中**。
2. **检索失败的错误传播**：检索异常/空结果时，retrieve_node 返回 `{"documents": []}` 让 generate_node 处理，还是覆写 `route_decision="fallback"` 让图路由到降级节点？换方案会改变图的执行路径和 route_decision 的语义边界。**命中**。

---

### 决策 1：节点依赖注入 — 工厂闭包模式

**语境**：LangGraph 节点函数签名固定为 `state: GraphState -> dict`，但三个节点都需要外部依赖：route_node 需要 LLM（意图分类）、retrieve_node 需要 RetrieverProtocol（检索）、generate_node 需要 LLM + Prompt + CitationExtractor（生成+引用）。这些依赖不在 GraphState 中——GraphState 是节点间的数据契约，不是依赖注入容器。

**候选对比**：

- **方案 A**：工厂闭包 — `create_workflow_nodes(retriever, llm, prompt)` 返回节点函数字典，依赖捕获在闭包中
  - 在本项目语境下的优势：依赖通过工厂参数显式注入，测试时传入 Mock 对象即可；节点函数仍保持 `state -> dict` 签名，与 LangGraph 完全兼容；与现有 factories.py 的工厂模式一脉相承
  - 在本项目语境下的硬伤：Task 2.3 必须先调用工厂函数才能获取节点函数，增加了一步间接调用

- **方案 B**：模块级导入 — 节点函数内部 `from src.core.config import settings; from src.core.factories import create_retriever`
  - 在本项目语境下的优势：节点函数是独立函数，无需工厂包装
  - 在本项目语境下的硬伤：节点与 config/factories 紧耦合，无法注入 Mock 进行单元测试；模块导入时有副作用（触发 settings 加载、Ollama 连接）；同一进程无法创建不同配置的图实例（如测试环境和生产环境并存）

- **方案 C**：类实例 + `__call__` — `class RouteNode: def __init__(self, llm): ...; def __call__(self, state): ...`
  - 在本项目语境下的优势：类型安全，IDE 自动补全完整
  - 在本项目语境下的硬伤：过度工程——三个节点本质上是无状态函数（依赖在创建时固定，运行时不变），用类包装增加了 `self` 间接层，读代码时需要跳转到 `__init__` 才能看到依赖

**反驳推演**：如果选方案 B，测试 retrieve_node 时必须 Mock `src.core.factories.create_retriever`（patch 模块级导入），而非直接传入 Mock retriever。如果 factories.py 的内部实现变化（如缓存策略调整），测试也需要同步修改。方案 A 的测试只需 `create_workflow_nodes(mock_retriever, mock_llm, mock_prompt)` ——依赖关系在调用点显式声明，不受内部实现变化影响。

**结论**：选 A，根本理由是本项目要求"核心逻辑可 Mock，依赖可注入"（质量准则第 9 维），工厂闭包是满足此要求的最轻量方案。如果节点函数不需要外部依赖（如纯状态变换节点），方案 B 足够——但本项目的三个节点都依赖 LLM/Retriever，方案 B 的紧耦合在测试时立即失效。

**反事实自检**：

- [x] 方案 B 不再失效（如果节点函数不需要外部依赖，或测试不需要 Mock），两方案都可行 → "三个节点都依赖 LLM/Retriever"正是让方案 B 失效的原因 → 验证通过

---

### 决策 2：检索失败的错误传播 — 返回空文档 vs 覆写路由决策

**语境**：当 retriever 抛出 RetrievalError 或返回空列表时，retrieve_node 有两种策略处理：(A) 返回 `{"documents": []}` 让 generate_node 处理空文档场景；(B) 返回 `{"documents": [], "route_decision": "fallback"}` 覆写路由决策，让 Task 2.3 的条件边跳转到降级节点。两种策略改变了 route_decision 字段的语义边界——是"路由节点的专属输出"还是"任何节点都可修改的公共标记"。

**候选对比**：

- **方案 A**：仅返回 `{"documents": []}`，不修改 route_decision
  - 在本项目语境下的优势：route_decision 保持"路由节点专属输出"的语义——只有 route_node 写入此字段，其他节点只读取；generate_node 已有空检索拦截逻辑（返回预设回复），无需路由到 fallback 节点；状态流转可预测：route_node → route_decision → 条件边 → retrieve_node → documents → generate_node
  - 在本项目语境下的硬伤：检索失败时的回复走 generate_node 的空检索逻辑，与 fallback 节点的降级回复可能措辞不同——但本项目两者的语义目标一致（告知用户无法回答），措辞差异可接受

- **方案 B**：返回 `{"documents": [], "route_decision": "fallback"}`
  - 在本项目语境下的优势：检索失败直接走降级路径，无需经过 generate_node
  - 在本项目语境下的硬伤：route_decision 的语义被污染——它不再是"意图分类结果"，而是"任意节点可修改的路由标记"。如果 retrieve_node 可以覆写 route_decision，那 generate_node 是否也可以？字段所有权模糊导致调试时无法确定 route_decision 的值来自哪个节点；且条件边在 retrieve_node 之后不会重新检查 route_decision（Task 2.3 的图结构是 route → retrieve → generate 线性流），覆写无实际效果

**反驳推演**：如果选方案 B，Task 2.3 的条件边需要在 retrieve_node 之后也检查 route_decision。但 Task 2.3 的图结构是 `route → [retrieve | fallback]`，retrieve_node 之后直接到 generate_node——没有从 retrieve_node 到 fallback_node 的条件边。这意味着方案 B 的覆写不会产生路由效果，只是修改了状态中的一个字段，但没有任何消费者读取它。

**结论**：选 A，根本理由是 Task 2.3 的图结构中 retrieve_node 之后无条件边检查 route_decision——覆写此字段无路由效果，反而模糊了字段所有权。如果 Task 2.6 的自适应路由在 retrieve_node 之后添加条件边（如"检索结果质量差则重试"），结论会反转——此时 retrieve_node 需要通过状态字段向条件边传递检索质量信号。

**反事实自检**：

- [x] 方案 B 不再失效（如果 retrieve_node 之后存在检查 route_decision 的条件边），两方案都可行 → "Task 2.3 的图结构中 retrieve_node 之后无条件边检查 route_decision"正是让方案 B 失效的原因 → 验证通过

---

### 质量准则豁免

无需豁免。10 维质量准则在本 Task 中均有具体落地方式（详见代码蓝图）。

---

## 模块结构

### 文件组织
```
src/workflow/
├── __init__.py      # 更新：导出 create_workflow_nodes
├── state.py         # 不变
├── routing.py       # 新增：路由逻辑独立模块
└── nodes.py         # 新增：节点函数 + 工厂函数
```

### 关键外部依赖（仅列非标准库）
```
routing.py
├── langchain_core.language_models  # BaseChatModel（LLM 类型注解）
├── langchain_core.prompts          # ChatPromptTemplate（路由 Prompt）
└── langchain_core.output_parsers   # StrOutputParser（解析 LLM 输出）

nodes.py
├── langchain_core.language_models  # BaseChatModel
├── langchain_core.prompts          # ChatPromptTemplate
├── langchain_core.documents        # Document
├── langchain_core.messages         # HumanMessage, AIMessage
├── src.workflow.state              # GraphState
├── src.workflow.routing            # classify_intent, VALID_ROUTE_DECISIONS
├── src.retriever.protocols         # RetrieverProtocol
├── src.retriever.base_retriever    # RetrievalError
├── src.generation.rag_chain        # format_docs
├── src.generation.citation_chain   # CitationExtractor
├── src.generation.exceptions       # CitationExtractionError
└── src.utils.retry                 # with_retry
```

### 职责边界
```
routing.py 职责：
✅ 包含：路由分类 Prompt 模板定义
✅ 包含：路由标签常量（RETRIEVE, GREETING, FALLBACK, VALID_ROUTE_DECISIONS）
✅ 包含：classify_intent(question, llm) 分类函数
❌ 不包含：节点函数定义 ← 属于 nodes.py
❌ 不包含：图构建逻辑 ← 属于 builder.py

nodes.py 职责：
✅ 包含：create_workflow_nodes 工厂函数（依赖注入 + 返回节点字典）
✅ 包含：route_node（意图分类 + 提取问题）
✅ 包含：retrieve_node（调用检索器）
✅ 包含：generate_node（LLM 生成 + 引用提取 + 迭代计数）
✅ 包含：节点级常量（EMPTY_RETRIEVAL_RESPONSE 等）
❌ 不包含：路由分类逻辑 ← 属于 routing.py
❌ 不包含：图构建 / 条件边逻辑 ← 属于 builder.py
```

### 与后续 Task 的接口衔接
- Task 2.3：`create_workflow_nodes(settings)` 返回的节点字典直接用于 `graph.add_node(name, func)`
- Task 2.4：节点函数签名不变，Checkpointer 自动序列化 GraphState
- Task 2.5：route_node 从 messages 提取问题，摘要压缩不影响 question 字段
- Task 2.6：classify_intent 可替换为自适应路由器（工厂闭包模式支持运行时替换）

---

## 错误处理策略

| 异常 | 捕获节点 | 处理方式 | 中断主流程？ | 理由 |
|------|---------|---------|------------|------|
| LLM 调用失败（路由） | route_node | 默认 `route_decision="retrieve"` | 否 | 乐观回退：让系统尝试检索，而非直接放弃 |
| RetrievalError | retrieve_node | 返回 `{"documents": []}` | 否 | generate_node 的空检索拦截会返回预设回复 |
| Exception（生成） | generate_node | 返回错误 AIMessage + 递增 iteration_count | 否 | 用户得到明确错误提示；iteration_count 递增防止无限循环 |
| CitationExtractionError | generate_node | 降级为 `citations=[]` | 否 | 引用提取是增强功能，不应中断主流程 |
| 一般 Exception | 所有节点 | 返回错误 AIMessage + 日志 | 否 | 防止未预期异常崩溃整个图 |

---

## 测试策略概要

### 可独立测试的函数/方法
- `classify_intent(question, mock_llm)`：纯函数，Mock LLM 返回预设分类结果
- `route_node(state)`：给定模拟 GraphState，验证返回值包含 `question` + `route_decision`
- `retrieve_node(state)`：给定模拟 GraphState + Mock retriever，验证返回 `documents`
- `generate_node(state)`：给定模拟 GraphState + Mock LLM，验证返回 `messages` + `iteration_count`

### Mock 边界
- **LLM**：Mock `BaseChatModel`，`invoke()` 返回预设 AIMessage
- **Retriever**：Mock `RetrieverProtocol`，`invoke()` 返回预设 Document 列表
- **CitationExtractor**：Mock 或使用真实实例（纯正则，无外部依赖）
- **with_retry**：在测试中不使用重试（Mock LLM 直接返回，不触发重试）

### 必须覆盖的关键测试场景
- **route_node**：问候问题 → "greeting"；知识库问题 → "retrieve"；无关问题 → "fallback"
- **route_node**：messages 中无 HumanMessage → question=""
- **retrieve_node**：正常检索 → documents 非空
- **retrieve_node**：RetrievalError → documents=[]
- **generate_node**：documents 非空 → messages 包含 AIMessage + iteration_count 递增
- **generate_node**：documents 为空 → 返回空检索预设回复 + iteration_count 递增
- **generate_node**：LLMCallError → 返回错误回复 + iteration_count 递增

---

## 代码蓝图：施工图纸级别

### routing.py

```python
"""路由逻辑模块 — 意图分类与路由决策。

本模块将路由逻辑从节点函数中分离，独立管理意图分类的 Prompt 和分类函数。

为什么路由逻辑独立为模块（设计决策）：
    1. 可测试性：classify_intent 可独立测试，无需构造完整 GraphState
    2. 可替换性：Task 2.6 自适应路由可替换此模块的 classify_intent，
       节点函数无需修改（依赖注入的是函数引用，不是模块）
    3. 职责单一：routing.py 负责"分类逻辑"，nodes.py 负责"状态管理"
"""
```

#### 路由标签常量

```python
# 与 GraphState.route_decision 的可能值严格对齐
RETRIEVE = "retrieve"    # 知识库问题 → 进入检索流程
GREETING = "greeting"    # 问候类 → 直接回复
FALLBACK = "fallback"    # 无法回答 → 降级处理
VALID_ROUTE_DECISIONS = (RETRIEVE, GREETING, FALLBACK)
```

#### 路由分类 Prompt

```python
# System Message：定义分类任务 + 分类规则 + 输出格式约束
ROUTE_SYSTEM_TEMPLATE = """你是一个意图分类器。根据用户的输入，判断其意图类别。

分类规则：
- greeting：问候、寒暄（如"你好"、"早上好"、"hi"）
- retrieve：知识库问题（技术文档相关的问题，需要检索文档来回答）
- fallback：无法回答的问题（与文档主题无关、超出知识库范围的闲聊或问题）

请只返回类别标签（greeting、retrieve、fallback），不要返回其他内容。"""

# Human Message：用户问题占位
ROUTE_HUMAN_TEMPLATE = "{question}"
```

#### create_route_prompt

```python
def create_route_prompt() -> ChatPromptTemplate:
    """创建路由分类 Prompt 模板。

    为什么是函数而非模块级变量（替代方案排除）：
        ChatPromptTemplate.from_messages 每次调用创建新实例，
        避免共享状态问题。与 generation/prompts.py 的 get_prompt 模式一致。
    """
    # 使用 ChatPromptTemplate.from_messages 组装
    # [SystemMessagePromptTemplate.from_template(ROUTE_SYSTEM_TEMPLATE),
    #  HumanMessagePromptTemplate.from_template(ROUTE_HUMAN_TEMPLATE)]
```

#### classify_intent

```python
def classify_intent(question: str, llm: BaseChatModel) -> str:
    """使用 LLM 对用户问题进行意图分类。

    为什么是独立函数而非 route_node 的一部分（设计决策）：
        1. 可测试性：可独立测试分类逻辑，无需构造完整 GraphState
        2. 可替换性：Task 2.6 自适应路由可替换此函数为更复杂的分类器
        3. 职责单一：route_node 负责"状态管理"（提取问题+写入决策），
           classify_intent 负责"分类逻辑"（调用 LLM+解析结果）

    为什么默认返回 "retrieve" 而非 "fallback"（反直觉辩护）：
        分类失败时，默认 "retrieve" 让系统有机会检索相关文档——
        即使检索为空，generate 节点也能返回有意义的空检索回复。
        默认 "fallback" 则直接放弃，用户无法获得任何有用信息。
        "宁可多走一步检索，也不直接放弃"是生产级系统的保守策略。

    流程：
        1. 创建路由 Prompt 模板
        2. 组装 LCEL 链：prompt | llm | StrOutputParser
        3. 调用链获取分类结果
        4. 解析结果：匹配有效标签 → 返回；无法匹配 → 默认 "retrieve"

    Args:
        question: 用户问题
        llm: Chat 模型实例

    Returns:
        路由标签："retrieve" / "greeting" / "fallback"

    Raises:
        无 — 所有异常内部处理，保证返回有效标签
    """
    # 步骤 1：创建路由 Prompt 模板
    # 调用 create_route_prompt()

    # 步骤 2：组装 LCEL 链
    # prompt | llm | StrOutputParser()

    # 步骤 3：调用链获取分类结果
    # chain.invoke({"question": question})
    # 日志：debug 记录原始分类结果
    # 异常处理：捕获所有异常 → 日志 warning + 默认返回 RETRIEVE

    # 步骤 4：解析结果
    #   ├─ 结果去除首尾空白 + 转小写 → 在 VALID_ROUTE_DECISIONS 中 → 返回标签
    #   ├─ 不在有效列表 → 尝试从结果中提取有效标签
    #   │   （处理 LLM 输出多余文本的情况，如 "The intent is: retrieve"）
    #   │   遍历 VALID_ROUTE_DECISIONS，检查 valid in label
    #   └─ 提取失败 → 记录 warning 日志，默认返回 RETRIEVE
    # 日志：warning 记录未识别的标签 + 回退决策
```

---

### nodes.py

```python
"""LangGraph 工作流节点函数 — 路由、检索、生成。

本模块定义三个核心节点函数，通过工厂闭包模式注入依赖。
Task 2.3 的 builder 调用 create_workflow_nodes 获取节点字典，
直接用于 graph.add_node(name, func) 注册。

核心设计：
1. **工厂闭包注入依赖**：节点函数不直接导入 config/factories，
   依赖通过 create_workflow_nodes 参数注入，支持 Mock 测试。
2. **节点职责单一**：每个节点只做一件事——路由节点只做意图分类，
   检索节点只做检索，生成节点只做生成。
3. **优雅降级**：每个节点捕获已知异常，返回错误状态更新，
   避免未处理异常崩溃整个图。
"""
```

#### 节点级常量

```python
EMPTY_RETRIEVAL_RESPONSE = (
    "抱歉，我在文档库中未找到与您问题相关的内容。"
    "请尝试换个方式提问，或确认您的问题与文档主题相关。"
)
"""空检索预设回复 — 与 RAGChain.EMPTY_RETRIEVAL_RESPONSE 措辞一致。

为什么不从 RAGChain 导入（反直觉辩护）：
    workflow 不应依赖 generation 模块（模块分离原则）。
    RAGChain 的常量是其内部实现细节，workflow 节点独立定义
    避免引入不必要的模块间依赖。两者措辞一致是当前决策，
    未来可能因节点上下文不同而分化。"""

GENERATION_ERROR_RESPONSE = (
    "抱歉，生成回答时遇到了问题，请稍后重试。"
)
"""生成失败预设回复 — LLM 调用失败时的降级响应。"""
```

#### create_workflow_nodes

```python
def create_workflow_nodes(
    retriever: RetrieverProtocol,
    llm: BaseChatModel,
    prompt: ChatPromptTemplate,
    citation_extractor: CitationExtractor | None = None,
    max_iterations: int = 3,
) -> dict[str, Callable[[GraphState], dict]]:
    """创建工作流节点函数（工厂函数，闭包模式注入依赖）。

    为什么用工厂闭包而非模块级导入（设计决策）：
        详见架构决策 1。

    为什么返回 dict 而非 namedtuple/dataclass（功能取舍）：
        LangGraph 的 add_node 期望 (name, func) 对，
        dict 的 key 自然对应节点名，value 对应节点函数。
        namedtuple 虽然有属性访问，但 add_node 不支持按属性注册。

    为什么 llm 同时用于路由和生成（功能取舍）：
        当前为简化实现，路由和生成共用同一 LLM 实例。
        工厂闭包模式支持未来分离——只需添加 route_llm 参数，
        route_node 使用 route_llm，generate_node 使用 llm。
        当前不做此分离，因为意图分类的延迟在可接受范围内。

    Args:
        retriever: 检索器（满足 RetrieverProtocol 即可，可 Mock）
        llm: Chat 模型实例（路由和生成共用，可 Mock）
        prompt: RAG 生成 Prompt 模板（非路由 Prompt）
        citation_extractor: 引用提取器，默认创建正则策略实例
        max_iterations: 最大迭代次数（安全阀阈值，默认 3）

    Returns:
        {"route": route_node, "retrieve": retrieve_node, "generate": generate_node}
    """
    # 步骤 1：初始化依赖
    # 注入：retriever、llm、prompt 均可 Mock

    # 步骤 1a：citation_extractor 默认创建 CitationExtractor()

    # 步骤 1b：构建 LCEL 生成链
    # prompt_llm_chain = prompt | llm（返回 AIMessage，用于带重试的同步调用）

    # 步骤 1c：创建带重试的 invoke 函数
    # retryable_invoke = with_retry(prompt_llm_chain.invoke, max_attempts=3, min_wait=4, max_wait=10)
    # 日志：info 记录节点工厂初始化完成（含 max_iterations）

    # 步骤 2-4：定义节点函数（见下方蓝图）

    # 步骤 5：返回节点字典
    # {"route": route_node, "retrieve": retrieve_node, "generate": generate_node}
```

#### route_node

```python
    def route_node(state: GraphState) -> dict:
        """路由节点：意图分类 + 提取当前问题。

        为什么同时写 question 和 route_decision（设计决策）：
            question 独立于 messages 是 Task 2.1 的设计决策（详见 state.py）。
            route_node 是唯一写入 question 的节点——
            后续节点（retrieve/generate）直接读取 state["question"]，
            无需关心 messages 的内部结构。

        为什么从 messages 提取问题而非接收参数（面试知识点）：
            LangGraph 节点函数签名固定为 state -> dict，
            用户的输入通过 messages 字段传入初始状态。
            路由节点是图中的第一个业务节点，负责"翻译"
            messages 中的用户输入为结构化的 question 字段。

        异常处理：
            LLM 分类失败 → 默认 "retrieve"（详见 classify_intent 的反直觉辩护）

        Returns:
            {"question": str, "route_decision": str}
        """
        # 步骤 1：从 messages 中提取最新用户问题
        # 反向遍历 state["messages"]，找到最后一条 HumanMessage
        #   ├─ 找到 → question = HumanMessage.content
        #   └─ 未找到 → question = ""（边界处理）
        #        日志：warning 记录"messages 中未找到 HumanMessage"
        # 日志：info 记录提取的问题（截断至 50 字符）

        # 步骤 2：调用 classify_intent 分类意图
        # route_decision = classify_intent(question, llm)
        # 日志：info 记录路由决策

        # 步骤 3：返回状态更新
        # {"question": question, "route_decision": route_decision}
```

#### retrieve_node

```python
    def retrieve_node(state: GraphState) -> dict:
        """检索节点：调用检索器获取相关文档。

        为什么直接调用 retriever.invoke() 而非 RAGChain.retrieve()（设计决策）：
            RAGChain.retrieve() 将 RetrievalError 包装为 GenerationError，
            这是为 RAGChain 的编排层设计的异常转换。
            LangGraph 节点需要更细粒度的异常控制——
            检索失败时返回空文档列表（而非抛异常），让 generate 节点
            处理"空检索"场景。如果使用 RAGChain.retrieve()，
            节点需要先解包 GenerationError 再重新处理，增加无谓的异常层级。

        为什么空文档不设置 route_decision="fallback"（反直觉辩护）：
            详见架构决策 2。route_decision 是路由节点的专属输出，
            retrieve_node 不应覆写。generate_node 会处理空文档场景。

        Returns:
            {"documents": List[Document]}
        """
        # 步骤 1：读取当前问题
        # question = state["question"]
        # 日志：info 记录开始检索

        # 步骤 2：调用检索器 + 异常处理
        # try:
        #     docs = retriever.invoke(question)
        # except RetrievalError as e:
        #     日志：error 记录检索失败 + error 字段
        #     docs = []  # 鲁棒性：回退为空列表，让 generate 节点处理
        # 日志：info 记录检索结果数量

        # 步骤 3：返回状态更新
        # {"documents": docs}
```

#### generate_node

```python
    def generate_node(state: GraphState) -> dict:
        """生成节点：调用 LLM 生成回答 + 引用提取 + 迭代计数。

        为什么同时递增 iteration_count 和写 messages（设计决策）：
            iteration_count 是安全阀的输入（Task 2.3 条件边检查），
            messages 是对话历史的累积。两者是不同维度的状态更新：
            - iteration_count: 控制流（防止无限循环）
            - messages: 数据流（对话内容）
            合并到同一个字段（如在 messages 中计数）会混淆控制流和数据流。

        为什么空文档时不调用 LLM（功能取舍）：
            空检索意味着没有相关上下文，调用 LLM 既浪费 API 配额，
            又增加幻觉风险（LLM 在无上下文时更倾向编造答案）。
            直接返回预设回复是更安全、更经济的选择。

        为什么复用 format_docs() 而非重新实现（替代方案排除）：
            format_docs() 已处理边界情况（空文档跳过、source 缺失回退），
            且输出格式与 Prompt V2 的 few-shot 示例严格一致。
            重新实现需要维护两处格式化逻辑，违反 DRY。

        异常处理：
            LLM 调用失败 → 返回错误 AIMessage + 递增 iteration_count
            引用提取失败 → 降级为无引用的回答（不中断主流程）

        Returns:
            {"messages": [AIMessage], "iteration_count": int}
        """
        # 步骤 1：读取状态
        # question = state["question"]
        # documents = state["documents"]
        # current_count = state["iteration_count"]

        # 步骤 2：空检索拦截
        #   ├─ documents 为空 → 返回空检索预设回复
        #   │   {"messages": [AIMessage(content=EMPTY_RETRIEVAL_RESPONSE)],
        #   │    "iteration_count": current_count + 1}
        #   └─ documents 非空 → 继续步骤 3
        # 日志：warning 记录空检索拦截

        # 步骤 3：格式化文档 + 提取来源
        # context = format_docs(documents)
        # sources = [doc.metadata.get("source", "") for doc in documents]

        # 步骤 4：调用 LLM 生成回答
        # try:
        #     ai_message = retryable_invoke({"context": context, "question": question})
        #     answer = ai_message.content
        #     # 提取 token 使用量（与 RAGChain._generate_step 一致）
        #     usage = getattr(ai_message, "usage_metadata", None) or {}
        #     日志：info 记录生成完成 + answer 长度 + token 使用量
        # except Exception as e:
        #     日志：error 记录生成失败 + error_type
        #     answer = GENERATION_ERROR_RESPONSE
        # 可观测性：步骤 4 的 try 块前记录 start = time.perf_counter()
        #           try/except 后计算 latency_ms

        # 步骤 5：引用提取（非致命，失败降级为空列表）
        # try:
        #     citations = citation_extractor.extract(answer, sources)
        #     日志：info 记录引用数量 + 有效引用数量
        # except CitationExtractionError:
        #     citations = []
        #     日志：warning 记录引用提取失败
        # 注意：当前 Task 不将 citations 写入状态（GraphState 无此字段），
        #       提取结果仅用于日志记录。TODO(Task 2.6): 评估是否需在状态中增加 citations 字段

        # 步骤 6：组装返回
        # answer_message = AIMessage(content=answer)
        # {"messages": [answer_message], "iteration_count": current_count + 1}
```

---

## 常见坑点

1. **messages 提取顺序**：`state["messages"]` 是按时间顺序排列的列表，最新的消息在列表末尾。提取用户问题时必须反向遍历（`reversed(state["messages"])`）找到最后一条 HumanMessage，否则在多轮对话中会提取到旧消息。

2. **iteration_count 必须在所有路径下递增**：无论是正常生成、空检索、还是 LLM 调用失败，generate_node 都必须递增 iteration_count。如果忘记在错误路径递增，安全阀机制失效——LLM 反复失败时图会无限循环。

3. **classify_intent 的 LLM 输出解析**：LLM 可能不严格遵守"只返回标签"的指令，可能返回 "The intent is: retrieve" 或 "retrieve\n" 等格式。解析时必须先 strip + lower，再在 VALID_ROUTE_DECISIONS 中查找子串匹配，最后才回退到默认值。

4. **format_docs 的导入路径**：从 `src.generation.rag_chain` 导入 `format_docs`，而非从 `src.generation` 导入。`format_docs` 是模块级函数，不在 `generation/__init__.py` 的 `__all__` 中。

5. **闭包中的变量捕获**：工厂闭包捕获的是变量引用，不是值。如果在工厂函数中修改了 `retriever` 等变量，所有节点函数都会看到修改后的值。当前实现不会修改这些变量，但要注意不要在节点函数内部意外修改闭包变量。

6. **route_node 是唯一写入 question 的节点**：后续节点（retrieve/generate）只读取 `state["question"]`，不应修改它。如果某个节点需要变换问题（如改写查询），应使用新的状态字段（如 `rewritten_question`），而非覆盖 `question`。
