# Task 2.6 文档评估与自适应路由 — 架构设计

> **原始需求**：`.project/outline/phase_2_langgraph/task_2.6_draft1.md`
>
> **涉及文件**：
> - `src/workflow/state.py`（修改 — GraphState 增 `rewrite_count`、`max_rewrite_count`；GraphContext 增 `max_rewrite_count`）
> - `src/workflow/prompts.py`（修改 — 新增 `DocumentGrade`、`GradeList` Pydantic models；`GRADE_PROMPT`、`REWRITE_PROMPT`）
> - `src/workflow/edges.py`（修改 — 新增 `route_after_grade` 路由函数；`TOOL_CALL` 常量）
> - `src/workflow/nodes.py`（修改 — `create_workflow_nodes` 新增 `grade_documents_node`、`rewrite_node` 闭包）
> - `src/workflow/builder.py`（修改 — 图拓扑重连：`retrieve→memory` 改为 `retrieve→grade→[rewrite↺|memory→generate]`）
> - `tests/test_graph_state.py`（修改 — Fixture 补充新字段）
> - `tests/test_workflow_nodes.py`（修改 — 新增 `TestGradeDocumentsNode`、`TestRewriteNode`）
> - `tests/test_workflow_builder.py`（修改 — 新增 `TestRouteAfterGrade`、`TestToolCallConstant`）

---

## 架构决策与权衡

### 先读：这不是"插一个评分节点"的事

从验收要求看，插入一个节点就能打分——但仔细拆解有 5 个不在表面上的结构性问题：

1. **grade_documents 要不要修改状态？** 官档把评分做在条件边里（返回节点名），但我们验收要求"部分相关时过滤文档"——条件边不能改状态，这决定了 grade 必须是节点而非路由函数，直接影响 LangGraph 图注册方式
2. **循环计数值在哪里递增？** grade 节点判定"全不相关"时递增→rewrite，还是 rewrite 节点执行时递增？条件边判断 `count < max` 是在 rewrite 前还是后？这影响状态中 `rewrite_count` 的语义和维护责任
3. **配置上限放哪？** 条件边函数签名只有 `(state) -> str`，拿不到 `GraphContext`。`max_rewrite_count` 放 state（入序列化）、放 context（条件边读不到）、还是闭包捕获（测试不直接）
4. **多少篇文档 = 多少次 LLM 调用？** 逐条评分(N×延迟) vs 批量评分(1×延迟)。验收要求"每一条独立评分"，没说一次只能评一条
5. **grade 节点要不要携带 rewrite_count 的状态更新？** 一个节点改两件事情（过滤文档 + 递增计数器）违反 SRP

---

### 入口判定

1. **grade_documents 节点 vs 路由函数**：换方案改变节点注册方式和条件边依赖形式（add_node vs add_conditional_edges 的 routing_function）。**命中**。

2. **rewrite_count 递增归属**：grade 节点 vs rewrite 节点。换方案改变 `route_after_grade` 的路由判断逻辑和 `rewrite_node` 的返回值。**命中**。

3. **max_rewrite_count 传递方式**：state 字段 vs GraphContext closure vs 模块常量。换方案改变条件边的可测试性、per-invoke 可配置性和 GraphState 的字段数。**命中**。

4. **评分粒度**：逐条 N 次 LLM vs 批量 1 次 LLM。换方案改变 grade_documents_node 内部的调用模式和延迟成本结构。**命中**。

5. **循环拓扑**：grade 后判断 vs generate 后判断。换方案改变图拓扑中条件边的源节点和 rewrite→retrieve 回边的挂载点。**命中**。

---

### 决策 1：grade_documents — 节点还是条件边路由函数？

**语境**：LangGraph 官方 Agentic RAG 教程将 `grade_documents` 实现为 `add_conditional_edges` 的路由函数，返回 `Literal["generate_answer", "rewrite_question"]`，不修改状态。但本 Task 的验收要求（部分相关→过滤、逐条评分）要求 grade 必须修改 `state["documents"]`。

**候选对比**：

- **方案 A — 独立节点**：`graph.add_node("grade", grade_documents_node)` → 返回 `{"documents": filtered}` → 再加独立条件边 `route_after_grade`
  - 本项目优势：可修改 state（过滤文档）、可逐条评分或批量评分、可加异常回退逻辑
  - 本项目硬伤：比官档方案多注册一个节点 + 一条条件边，图结构稍微复杂

- **方案 B — 路由函数**：`graph.add_conditional_edges("retrieve", grade_documents)` → 路由函数内调用 LLM 评分 → 返回节点名
  - 本项目优势：与官档完全对齐，图更简洁
  - 本项目硬伤：不能修改 state["documents"]，无法实现"部分相关→过滤不相关文档"。验收约束 1.2 不满足

**反驳推演**：选方案 B，在 `grade_documents` 路由函数里无法修改 `state["documents"]` 来过滤不相关文档。结果是即使用 LLM 判断出某篇不相关，也无法阻止它进入 generate 节点——generate 收到的是原始检索结果，评估形同虚设。唯一的变通是在 generate 内部再做一次过滤，但这把评估职责推给了生成节点，打破 SRP，且 generate 已有空文档/正常文档两条路径，再加入"部分相关"分支，逻辑复杂度翻倍。

**结论**：选方案 A，根本理由是验收约束 1.2 要求"部分相关时过滤"——这是对 state 的写入操作，路由函数（state→str）不能写 state。如果验收标准改成"只要有一条相关就全部送 generate，有一条不相关就全部 rewrite"，方案 B 可行。

**反事实自检**：拿掉"部分相关→过滤"约束后——
- [x] 方案 B 不再失效，两方案都可行（A=节点+边，B=纯路由函数，选哪个是风格偏好）→ 该约束正是让方案 B 失效的原因 → 验证通过

---

### 决策 2：rewrite_count 在哪递增？

**语境**：rewrite 循环需要计数器防止无限改写。计数器必须在一轮 rewrite 结束后、条件边下次判断前递增。递增时机有两个候选点。

**候选对比**：

- **方案 A — grade 节点递增**：`grade_documents_node` 判定"全不相关"时 `rewrite_count += 1`
  - 本项目优势：grade 的返回值中顺便递增，一个点维护计数逻辑
  - 本项目硬伤：条件边 `route_after_grade` 在 grade 节点执行**后**触发，此时 `state["rewrite_count"]` 已经 +1。条件边判断 `count < max` 时，实际可用的 rewrite 次数少了 1 次（max=1 时，grade 后 state 已是 1，条件边：1<1？false → 直接降级，0 次 rewrite）

- **方案 B — rewrite 节点递增**：[交叉验证：Plan agent 建议] `rewrite_node` 执行改写时 `rewrite_count += 1`
  - 本项目优势：条件边 `route_after_grade` 在 grade 节点执行后触发时，count 尚未递增——判断 `count < max` 后再放行到 rewrite，rewrite 执行时再递增。max=1 时，第一次 grade 后 count=0，0<1 → rewrite(inc)→第二次 grade 后 count=1，1<1？false → 降级。正好 1 次 rewrite
  - 本项目硬伤：计数逻辑在 rewrite 节点，和 grade 节点分布在两处

**反驳推演**：选方案 A，max_rewrite_count=1 时，第一次 grade 后 rewrite_count=1，条件边看到 1<1 为 false → 直接降级。用户预期的是"尝试 1 次改写"，实际得到 0 次。这个 bug 在单元测试中能测出来→但要么改条件边逻辑为 `<=`（让语义变奇怪），要么改条件边在 grade 前判断（但 LangGraph 的 add_conditional_edges 只会在节点执行后触发，无法在节点执行前判断）。

**结论**：选方案 B，根本理由是条件边的触发时序：节点执行后 → 条件边判断。grade 递增会让 count 的"编程者可见值"比"条件边判断时的值"多 1。如果 LangGraph 允许"在 grade 返回途中拦截返回值做条件判断"（即不将 grade 的返回值写入 state 就触发条件边），结论会反转。

**反事实自检**：拿掉"条件边在 grade 节点 state 更新后触发"这一 LangGraph 约束后——
- [x] 方案 A 不再失效，两方案都可行 → 该约束正是让方案 A 失效的原因 → 验证通过

---

### 决策 3：max_rewrite_count 放哪？

**语境**：条件边 `route_after_grade(state: GraphState) -> str` 只能接收 state，无法访问 runtime 或全局配置。`max_rewrite_count` 是配置值，但条件边需要它来做路由判断。

**候选对比**：

- **方案 A — GraphState 字段**：[交叉验证：Plan agent 建议] `max_rewrite_count: int` 直接作为 GraphState 字段，每次 invoke 时从初始状态传入
  - 本项目优势：条件边直接 `state.get("max_rewrite_count", 1)` 读取，纯函数可测；per-invoke 可配（每次 invoke 传不同的初始值）；不需要 closure 间接层
  - 本项目硬伤：配置值进入 GraphState 会被 checkpoint 序列化；语义上"配置"不应和数据混在一起

- **方案 B — GraphContext → closure 捕获**：builder 构建时从 Settings 读取，闭包捕获到条件边函数中
  - 本项目优势：不污染 GraphState，配置纯在构建时确定
  - 本项目硬伤：条件边不可直接测试（闭包内部的配置值不可见，需间接验证）；如果 graph 是长生命周期单例（如 FastAPI 启动时构建一次），所有 invoke 共享同一个 max_rewrite_count，无法按请求调整

- **方案 C — 模块级常量**：`MAX_REWRITE_COUNT = 1` 作为 edges.py 常量
  - 本项目优势：最简单
  - 本项目硬伤：不可配置，验收约束硬性要求"可配置的硬性上限"

**反驳推演**：选方案 B，测试 `route_after_grade` 时无法直接构造不同 max_rewrite_count 的场景，必须走 builder 或通过 indirect inspection 验证闭包值。更重要的是，如果未来需求变为"根据用户等级决定改写次数"（如免费用户 1 次、付费用户 2 次），closure 模式需要重建 graph 或曲线救国（引入额外间接层）。方案 A 只需在 invoke 时传不同的 `max_rewrite_count` 初始值。

**结论**：选方案 A，根本理由是条件边函数只能接收 state，`max_rewrite_count` 放在 state 是测试直接、配置灵活、且不违反任何框架约束的方式。序列化代价是一个 int（约 24 字节）。如果未来有大量"配置伪装成数据"的字段膨胀到污染 GraphState，可通过 `input_schema` 过滤入站字段分离配置和业务数据。

**反事实自检**：将"条件边只能接收 state"从约束中移除——
- [ ] 方案 A 不再失效，两方案都可行 → 该约束正是让方案 A 胜出的原因 → 验证通过

---

### 决策 4：逐条评分 vs 批量评分

**语境**：验收约束 1.1 要求"对每一条检索结果独立输出相关性评分"。这可以逐条调用 LLM 也可以一次批量调用。

**候选对比**：

- **方案 A — 批量评分**：[交叉验证：Plan agent 建议] `GradeList(grades: list[DocumentGrade])` 一次 LLM 调用返回所有评分
  - 本项目优势：延迟 ≈1 次 LLM 调用（~500ms）；实现简单：一条 prompt 列出所有文档，`with_structured_output(GradeList)` 解析
  - 本项目硬伤：理论上 LLM 可能产生跨文档关联偏差（将相似文档的评分拉近）

- **方案 B — 逐条评分**：`for doc in docs: chain.invoke({"document": doc, "question": question})`
  - 本项目优势：严格独立，无跨文档偏差；prompt 更聚焦（单文档评分）
  - 本项目硬伤：N=5 时延迟 ≈5 × 500ms = 2.5s；实现稍复杂（循环 + 结果聚合）

**反驳推演**：选方案 B，在实际检索结果中检索回来的文档差异通常较大（不同来源/不同角度），LLM 不太可能因为"前一篇给了 yes"而倾向于对下一篇也给 yes。跨文档关联偏差在理论上存在但在实践中影响极小。相反，2.5s vs 0.5s 的延迟差距在任何实时问答场景中都不可忽略。

**结论**：选方案 A，根本理由是 N 篇文档的延迟成本在实际中不可接受，且跨文档关联偏差在检索结果多样性足够（>3 篇不同来源）时影响可忽略。如果检索器返回单篇长文档的分块（chunks 之间内容高度重叠），结论会反转——此时需要逐条确保每块独立可引用。

**反事实自检**：拿掉"检索结果来自不同来源、内容多样性足够"约束——
- [x] 方案 A 不再失效，两方案都可行 → 该约束正是让方案 A 可以用的前提 → 验证通过

---

### 非关键决策确认

#### 决策 1：循环拓扑 — grade 后判断 vs generate 后判断

- **方案 A — grade 后判断**：`retrieve → grade → [rewrite↺ | memory→generate]`
  - 优点：不白跑 generate；条件边直接读 `state["documents"]`
- **方案 B — generate 后判断**：`retrieve → grade → memory → generate → [END | rewrite↺]`
  - 缺点：白跑一次 generate（生成后再被告知文档不相关，需要重写→重检索→重生成）
- **结论**：选方案 A。generate 调用 token 成本高，不应该白跑。

#### 决策 2：独立 `rewrite_count` 字段 vs 复用 `iteration_count`

- **方案 A — 独立字段**：`rewrite_count` 和 `iteration_count` 分开
  - 优点：上限不同（1 vs 3）、递增时机不同（rewrite 节点 vs generate 节点），分开语义清晰
- **方案 B — 复用**：两个逻辑共用一个计数器
  - 缺点：上限互相绑架；rewrite 后不会立即走 generate，`iteration_count` 不递增
- **结论**：独立字段。

#### 决策 3：降级路径复用 generate 空文档路径 vs 新增 fallback2 节点

- **方案 A — 复用**：条件边走 `memory→generate`，generate 中 `documents=[]` 返回 `EMPTY_RETRIEVAL_RESPONSE`
  - 优点：不需要新节点、generate 已有空文档处理逻辑；memory 节点仍然压缩 chat_history
- **方案 B — 新增节点**：新增 `degradation` 节点返回预设回复
  - 缺点：冗余节点，generate 的空文档路径本身就是为这个场景设计的
- **结论**：复用。

#### 决策 4：grade 失败时保留全部 vs 保留空列表

- **方案 A — 保留全部**：`with_structured_output` 失败或长度不匹配时，`{"documents": docs}`（原样返回）
  - 优点：假阳性（不相关文档进 generate）比假阴性（相关文档被过滤）危害小
- **方案 B — 保留空列表**：返回 `{"documents": []}`
  - 缺点：相关的文档被丢弃，generate 无法基于真实上下文回答问题
- **结论**：保留全部。在"我们可能漏掉什么"和"我们可能放进来什么"之间，前者对本系统危害更大。

---

### 与后续 Task 的接口衔接

- Phase 4 工具调用：边缘模块 `edges.py` 预注册 `TOOL_CALL = "tool_call"` 常量，`route_after_grade` 函数体中当前不返回此值。Phase 4 在条件边中添加路由映射即可启用。

**已知后续替换**：

> 当前 `grade_documents_node` 使用同步 `llm.with_structured_output(GradeList).invoke()`。
> Phase 4 若引入异步 LangGraph（`async` 节点），需切换为 `await llm.with_structured_output(GradeList).ainvoke()`，且 `rewrite_node` 的 `llm.invoke` 同步调用同步切换。
> 接口不变（`(state) -> dict` 签名不受 async/await 影响），调用方式改，`create_workflow_nodes` 工厂返回的闭包签名不变——调用方只需从 `invoke` 切换为 `ainvoke`。

---

### 质量准则豁免

- **可扩展性**：不适用。Task 2.6 已包含本 Task 范围所需的全部扩展点（`TOOL_CALL` 预注册、`route_after_grade` 条件边映射表），超出本 Task 的扩展非当前可预期。

---

## 模块结构

### 文件组织
```
src/workflow/
├── state.py    # 状态字段：新增 rewrite_count、max_rewrite_count
├── prompts.py  # Pydantic models：DocumentGrade、GradeList；GRADE_PROMPT、REWRITE_PROMPT
├── edges.py    # 新增路由函数 route_after_grade、常量 TOOL_CALL
├── nodes.py    # 节点：grade_documents_node、rewrite_node（在 create_workflow_nodes 工厂中）
├── builder.py  # 图拓扑：retrieve→grade→[rewrite↺|memory→generate]
└── __init__.py # 无需改动（导出列表不受影响）
```

### 关键外部依赖
```
prompts.py
├── pydantic.BaseModel  # DocumentGrade、GradeList 结构化输出（已安装 v2.12.5）

nodes.py
├── langchain_core.language_models.BaseChatModel  # with_structured_output（已在 factory 中注入）
└── pydantic.BaseModel  # 已通过 prompts.py 导入
```

### 职责边界
```
state.py 职责：
✅ 包含：状态字段定义（rewrite_count、max_rewrite_count）
❌ 不包含：路由函数、节点逻辑 → 属于 edges.py / nodes.py

prompts.py 职责：
✅ 包含：评估/改写 Prompt 模板、结构化输出 Pydantic model
❌ 不包含：节点内部调用链 → 属于 nodes.py

nodes.py (create_workflow_nodes 工厂) 职责：
✅ 包含：grade_documents_node 评分+过滤、rewrite_node 改写+计数
❌ 不包含：图注册、边连接 → 属于 builder.py
❌ 不包含：GraphContext 依赖 → 纯函数 (state) -> dict

builder.py 职责：
✅ 包含：节点注册、边连接、条件边 path_map
❌ 不包含：节点逻辑本身 → 属于 nodes.py
```

---

## 错误处理策略

| 异常场景 | 节点 | 处理方式 | 是否中断主流程 | 理由 |
|---------|------|---------|-------------|------|
| `with_structured_output` 返回格式异常（JSON 解析失败） | grade_documents_node | 保留所有文档（保守回退） | 否 | 假阳性危害 < 假阴性 |
| GradeList 长度 != 文档数 | grade_documents_node | 保留所有文档 | 否 | 同上 |
| rewrite_node LLM 调用失败 | rewrite_node | 保留原问题，`rewrite_count` 仍递增 | 否 | 该次尝试已发生，计入上限 |
| rewrite_node 空问题输入 | rewrite_node | 不调用 LLM，仅递增 count | 否 | 空问题无法改写 |
| grade 空文档输入 | grade_documents_node | 返回 `{}`（不调 LLM） | 否 | 无文档可评 |

**分级说明**：
- **不中断主流程（继续）**：所有 grade/rewrite 异常都被节点内部捕获，回退后仍进入下一个节点，图继续执行。这是"鲁棒性"维度的设计——一个节点的失败不影响整个图的执行。
- **不抛异常**：所有失败路径都通过日志（warning 级别）记录，不向上传播。generate 节点已有自己的空文档处理逻辑，grade 保留所有文档后，generate 按正常流程走。

---

## 测试策略概要

### 可独立测试部分

| 函数 | 类型 | 测试策略 |
|------|------|---------|
| `route_after_grade(state) -> str` | 纯函数 | 直接构造不同 state 测试所有分支（有文档、无文档+count<max、无文档+count>=max） |
| `grade_documents_node(state) -> dict` | 闭包（Factory-injected LLM） | MagicMock 替换 `llm.with_structured_output`，预设 GradeList 返回值 |
| `rewrite_node(state) -> dict` | 闭包（同上） | FakeChatModel 预设 rewrite 内容；FailingChatModel 验证 LLM 失败回退 |
| `GradeList` / `DocumentGrade` | Pydantic model | 直接构造验证字段类型 |

### Mock 策略

- **LLM**: `MagicMock(spec=BaseChatModel)` 用于 `with_structured_output` 场景（需要 mock chain 返回值）；`FakeChatModel` 用于标准 `invoke` 场景（route、rewrite）。两者不可互换——`FakeChatModel` 不 mock `with_structured_output`，`MagicMock` 不支持 `|` 操作符
- **Retriever**: 复用现有 `mock_retriever` fixture（MagicMock）

### 关键测试场景

1. grade_documents：全部相关/全部不相关/混合/空文档/LLM 失败/长度不匹配
2. rewrite_node：正常改写/LLM 失败/空问题/纯函数签名验证
3. route_after_grade：有文档→memory/无文档+未超限→rewrite/无文档+已达上限→memory/默认值测试
4. TOOL_CALL 常量存在

---

## 代码蓝图：施工图纸级别

### 1. `src/workflow/state.py` — GraphState 新增字段

**插入位置**：`summary` 字段之后、`@dataclass GraphContext` 之前。

```python
rewrite_count: int
"""重写计数器 — rewrite 节点执行时递增。
为什么不在 grade 节点递增（设计决策）：
    条件边在 grade 执行后触发。若 grade 已递增，条件边看到的是
    post-increment 值，判断 count < max 时有效 rewrite 次数少 1。
    递增放在 rewrite 节点：条件边判断时 count 尚未变，判断通过后
    rewrite 执行时再递增。max=1 时正好产生 1 次 rewrite。"""

max_rewrite_count: int
"""查询改写硬性上限 — 直接放在 GraphState 而非闭包。
为什么不在条件边闭包中捕获（设计决策）：
    条件边函数签名 fn(state) -> str 只能接收 state。
    closure 捕获的配置值测试不直接（需要间接测闭包）。
    存入 state 后条件边 state.get("max_rewrite_count", 1) 读取，
    纯函数可测，per-invoke 可配。"""
```

**GraphContext 同步追加**：
```python
max_rewrite_count: int = 1
```

### 2. `src/workflow/prompts.py` — Pydantic models + 模板

**插入位置**：`FEW_SHOT_EXAMPLES` 之后、`PROMPT_REGISTRY` 之前。

```python
# Task 2.6: DocumentGrade 和 GradeList 定义
class DocumentGrade(BaseModel):
    """单篇文档的二元相关性评分"""
    binary_score: str = Field(
        description="Relevance score: 'yes' if relevant, 'no' if not"
    )

class GradeList(BaseModel):
    """批量文档评分结果 — 一次性返回所有评分列表。
    为什么用 list 而非逐条调用（设计决策）：
        N 条文档逐条评分延迟 = N × ~500ms。
        批量评分 1 次 LLM 调用即可，跨文档关联偏差
        在检索多样性足够时影响可忽略。"""
    grades: list[DocumentGrade] = Field(
        description="Grades for each document, in input order"
    )
```

```python
# Task 2.6: GRADE_PROMPT 和 REWRITE_PROMPT
GRADE_PROMPT = """..."""
REWRITE_PROMPT = """..."""
```

### 3. `src/workflow/edges.py` — 路由函数 + 预注册常量

**新增模块级常量**：
```python
TOOL_CALL = "tool_call"
"""Phase 4 预注册。当前不路由到此分支。"""
```

**新增纯函数** `route_after_grade(state: GraphState) -> str`：
```python
# 步骤 1：读取 state.documents、state.rewrite_count、state.max_rewrite_count
#   ├─ documents 非空                → "memory"（正常生成）
#   ├─ documents 为空 + count < max  → "rewrite"（改写后重试）
#   └─ documents 为空 + count >= max → "memory"（降级，generate 处理空文档）
```

### 4. `src/workflow/nodes.py` — 创建两个新闭包

**位置**：`retrieve_node` 闭包之后（grade_documents_node）、`generate_node` 之前（rewrite_node）。

**grade_documents_node(state: GraphState) -> dict**：

```python
# 步骤 1：读取 state.question、state.documents
#   ├─ documents 为空 → 返回 {}（不调 LLM，无文档可评）
#   └─ documents 非空 → 继续步骤 2
#
# 步骤 2：构建批量评分 prompt（列出所有文档，标序号）
#         调用 llm.with_structured_output(GradeList).invoke(...)
#         日志：info 记录文档数、评分耗时
#
# 步骤 3：验证结果长度 len(result.grades) == len(docs)
#   ├─ 不匹配 → warning 日志 + 保留所有文档 → 返回
#   └─ 匹配 → 继续步骤 4
#
# 步骤 4：zip(docs, result.grades)，仅保留 binary_score == "yes"
#         返回 {"documents": filtered}
# 异常处理：with_structured_output 抛异常 → warning 日志 + 保留所有文档 → 返回
#
# 为什么失败时保留全部而非清空（功能取舍）：
#     假阳性(不相关文档进 generate)导致回答质量下降但仍是"基于文档的回答"；
#     假阴性(相关文档被过滤)导致 generate 基于空文档返回"无法回答"——前者容忍度更高。
```

**rewrite_node(state: GraphState) -> dict**：

```python
# 步骤 1：读取 state.question、state.rewrite_count

# 步骤 2：question 为空 → 不调 LLM，返回 {"rewrite_count": count + 1}
#
# 步骤 3：调用 llm.invoke，传入 [HumanMessage(content=REWRITE_PROMPT.format(question=question))]
#         提取 response.content.strip()
#         ├─ 空 → 保留原 question
#         └─ 非空 → 使用改写后问题
#         日志：info 记录改写前后问题
#
# 步骤 4：返回 {"question": rewritten, "rewrite_count": count + 1}

# 异常处理：LLM 抛异常 → warning 日志 + 保留原 question + 仍递增 count
#
# 为什么 LLM 失败仍递增 count（设计决策）：
#     rewrite 尝试已经发生（网络请求发出并超时），
#     该次尝试计入上限——否则 max_rewrite_count 失去安全阀意义。
```

### 5. `src/workflow/builder.py` — 图拓扑变更

**节点注册**（add_node 调用处，按顺序插入 `retrieve` 和 `memory` 之间）：
```python
graph.add_node("grade", nodes["grade"])
graph.add_node("rewrite", nodes["rewrite"])
```

**边拓扑变更**（替换现有 `retrieve→memory` 直接边）：
```python
# 删除：graph.add_edge("retrieve", "memory")
# 新增：graph.add_edge("retrieve", "grade")
#
# 新增：graph.add_conditional_edges(
#     "grade",
#     route_after_grade,
#     { "rewrite": "rewrite", "memory": "memory" },
# )
#
# 新增：graph.add_edge("rewrite", "retrieve")
#
# 保留：graph.add_edge("memory", "generate")
```

**预期图拓扑**：
```
START → route → [retrieve | greeting | fallback]
retrieve → grade → [rewrite → retrieve]  (rewrite_count < max_rewrite_count)
                   → [memory → generate → END]  (相关 / 降级)
greeting → END
fallback → END
```
