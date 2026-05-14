# Task 2.6 文档评估与自适应路由 — 综合评价

> **自评**（第一方）+ **Agent 评**（第三方）
> 评价对象：设计文档（`.project/tasks/phase_2/task_2.6_design.md`）· 代码（`src/workflow/state.py` · `src/workflow/prompts.py` · `src/workflow/edges.py` · `src/workflow/nodes.py` · `src/workflow/builder.py`）· 技术文档（`task_2.6_navigator.md` · `task_2.6_anchor_01_agentic_rag.md` · `task_2.6_anchor_02_cycle_counter.md` · `task_2.6_anchor_03_structured_output.md`）

---

## 总体概要

**设计文档**：6 个决策的候选方案对比和反驳推演质量高——每项决策的反驳精确推导了被拒方案在 LangGraph 框架约束下如何失效。条件边签名 `fn(state) -> str` 作为根约束贯穿 3 个决策的推理链，没有"共用 Settings 作为输入"这种表面关联。但**代码蓝图中的 GRADE_PROMPT 与实现存在偏离**：蓝图定义了常量但节点使用了独立的 inline prompt。

**代码**：`grade_documents_node` 和 `rewrite_node` 故障处理路径完整（try/except 回退、长度校验、空文档拦截），单元测试覆盖边界充分。但**GRADE_PROMPT 跨语言指导未被内联 prompt 继承**——核心的"按语义评分而非语言"指导在实现中缺失。

**技术文档**：领航员的约束链结构有效（从条件边签名出发，追踪 3 个决策的形成过程），不存在"锚点摘要拼接"。锚点叙事切入点准（均从源码具体行为出发），反事实检验具体。但 Anchor ① 和 ③ 分别缺少条件边误解根源和 tool calling schema 注入格式的展开。

---

## 发现汇总

| ID | 严重度 | 自评 | Agent 评 | 描述 | 位置 |
|----|--------|------|----------|------|------|
| F1 | **严重** | 未发现 | **发现** | `GRADE_PROMPT` 常量定义并导出但未被 `grade_documents_node` 使用——节点使用独立内联 prompt；且内联 prompt 缺失跨语言指导（"按语义评分，非语言匹配"），导致跨语言场景下英文文档可能被全部判定为"不相关" | `prompts.py:215` vs `nodes.py:223-229` |
| F2 | **严重** | 发现 | 发现 | `GraphContext.max_rewrite_count` 定义但无代码路径读取——条件边从 `GraphState` 读取，context 中的值从未被使用 | `state.py:192` |
| F3 | 主要 | 发现 | 发现 | `grade_documents_node` 成功路径无日志——所有异常路径有 `logger.warning`，但正常评分无 `logger.info` | `nodes.py:247-253` |
| F4 | 主要 | 未发现 | **发现** | `rewrite_node` 使用裸 `llm.invoke()` 而 `generate_node` 使用 `retryable_invoke(,1;带重试)——行为不一致 | `nodes.py:284` vs `366` |
| F5 | 主要 | 未发现 | **发现** | 两处 GraphState 构造缺少 `rewrite_count` 和 `max_rewrite_count` 字段，在 `TypedDict` 运行时无校验的环境下构成维护陷阱 | `test_workflow_nodes.py:843, 869` |
| F6 | 次要 | 发现 | 未发现 | `test_empty_question` 断言 `"question" not in result or result["question"] == ""` 中 `or` 右侧不可达 | `test_workflow_nodes.py:723` |
| F7 | 次要 | 未发现 | **发现** | `_make_state` 辅助函数在不同测试文件中重复定义（`test_workflow_builder.py` 和 `test_graph_state.py`），未来加字段需同步修改多处 | 跨文件 |
| F8 | 次要 | 未发现 | **发现** | TODO 注释位置不准确：`builder.py:167` 标注 `TOOL_CALL` 关联，但 `TOOL_CALL` 定义在 `edges.py` | `builder.py:167` |
| F9 | 建议 | 未发现 | **发现** | 缺少完整的 grade→rewrite→retrieve→grade 端到端集成测试，当前仅覆盖独立单元和条件边 | `tests/` |

---

## 详细评价

### 一、设计文档

#### 优势

1. **根约束驱动推理**：设计文档不是"按决策编号逐条罗列"，而是从条件边签名 `fn(state) -> str` 出发，追踪其两条含义（不能写 state、只能接收 state）如何分别约束决策 1、2、3。这种约束链结构在 .5 review 中不存在，是 .6 设计文档的创新点。

2. **反驳推演的质量**：决策 2（rewrite_count 递增归属）的反驳精确到时序窗口：先 trace 出 `grade_node 执行 → state 合并 → 条件边触发` 的时序，再代入 `max=1` 的具体数值，证明方案 A 产生的是 0 次 rewrite 而非 1 次。不是定性判断，是定量推导。

3. **反事实自检的双向性**：每项自检都同时验证了"被拒方案在什么条件下成立"和"当选方案在什么条件下不再是最优"。例：决策 4 的自检既确认了"检索多样性足够"是批量评分的前提，也指出了当 chunks 高度重叠时结论反转。

4. **反事实自检的具体性**：每项自检都精确指向了让被拒方案可行的条件——LangGraph 时序变化、条件边签名变更、检索多样性下降。不存在"假设网络可用"这类泛泛之谈。

#### 问题

**F1（严重）**：`prompts.py` 中定义的 `GRADE_PROMPT` 常量包含跨语言指导（"not language match"），但 `grade_documents_node` 的内联 prompt 完全未继承这部分内容。直接后果：用户用中文提问、LLM 看到英文文档时，大概率给出"不相关"评分——整个跨语言 RAG 核心用例被破坏。设计蓝图在这一点上与实现偏离。

**修复**：已将跨语言指导融入内联 prompt，移除未使用的 `GRADE_PROMPT` 导出。注意：删除的是公共 API 导出，`GRADE_PROMPT` 常量本身保留在 `prompts.py` 中作为单文档评分模板的参考。

---

### 二、代码

#### 优势

1. **故障路径覆盖完整**：`grade_documents_node` 覆盖了 5 种异常（空文档快速返回、JSON 解析失败、长度不匹配、混合相关性、全部不相关），每种都有明确回退策略。`rewrite_node` 覆盖了空问题和 LLM 失败两种场景，失败后仍递增 count 保证了安全阀的可靠性。

2. **条件边的纯函数测试**：`route_after_grade` 的 5 个测试用例精确覆盖了所有路由组合（有文档、无文档+count<max、无文档+count>=max、默认值、超过上限）。函数签名 `(state) -> str` 的纯函数特性使测试无需 mock。

3. **`TestGradeDocumentsNode` 的 mock 策略恰当**：`TestGradeDocumentsNode` 的 mock 策略恰当。`test_structured_output_failure` 通过配置 `side_effect=Exception` 触发了完整的异常路径。`test_grade_result_length_mismatch` 构造了 2 个 grade 对应 1 个文档的场景——直接验证了长度检查逻辑。

#### 问题

**F3（主要）**：`grade_documents_node` 成功路径无日志。异常时 `logger.warning` 记录充分，但正常评分完成时没有任何信息（仅 know 被调用过，不知输出了几个/保留了几个）。生产环境中无法区分"全部相关"和"部分相关"之间的比例。

- **修复**：已添加 `logger.info`，记录 `input_count` 和 `output_count`。

**F4（主要）**：`rewrite_node` 使用 `llm.invoke()` 而 `generate_node` 使用 `retryable_invoke`。如果 LLM 暂时不可用，rewrite 立即失败（保留原问题），generate 会自动重试。不一致但无害：rewrite 失败的影响有限（仍递增 count、保留原问题），不危及数据安全。

- **不修复，保留注释说明**：`rewrite_node` 的 LLM 调用失败代价低（保留原问题、仍递增 count），增加重试带来的延迟风险 > 可靠性收益。如果未来 rewrite 的失败率过高，再统一为 `retryable_invoke`。

**F5（主要）**：`test_full_pipeline_route_then_retrieve` 和 `test_full_pipeline_all_three_nodes` 构造 GraphState 时未包含 `rewrite_count` 和 `max_rewrite_count`。TypedDict 运行时不报错，但若某天代码在协作 pipeline 中读取这些字段（比如 `state.get("rewrite_count", 0)` 返回 0 意外符合断言但实际上从未被核心逻辑使用），测试可能通过但行为错误。

- **修复**：已补全两处 GraphState 构造。

---

### 三、技术文档

#### 优势

1. **约束链领航员（最大亮点）**：从"条件边签名"根约束出发，追踪 3 条约束链（grade 为节点、rewrite_count 递增归属、max_rewrite_count 在 state）。每条链以"决策 → 签名位置 → 反事实条件"收尾。读者读完锚点后仍然缺的拼图正是"为什么一个 `fn(state) -> str` 决定了三件事"——领航员填补了这个缺口。

2. **Anchor ① 的条件边机制展开**：指出 `add_conditional_edges("A", router)` 的反直觉之处——路由函数的输入不是 A 的返回值，而是 A 返回值合并后的 state。这对没有阅读过 LangGraph 源码的读者是重要的澄清。

3. **Anchor ② 的时序窗口分析**：将 grade_node / rewrite_node 递增方案分别 trace 为两套时序图（"谁先看到 count"），然后代入 `max=1` 的数值验证——两个方案在纸上等价，在 LangGraph 的触发时序下不等价。验证过程可复现、可反驳。

4. **Anchor ③ 的失效模式分类**：将 `with_structured_output` 的失效分为"格式级"和"语义级"两类——前者对应 JSON 解析异常，后者对应长度不匹配。这种分类比"返回错误 / 返回不完整"更有区分力。

---

## 双评差异

| 方面 | 自评发现 | Agent 额外发现 |
|------|---------|--------------|
| 核心逻辑 | 条件边时序分析完整 | **F1**: GRADE_PROMPT 未使用 + 跨语言指导缺失（严重） |
| 配置与数据 | M1: GraphContext 死代码 | F1（同上，从不同角度发现同一问题） |
| 测试覆盖 | 测试层次结构合理 | **F4/F5**: rewrite 无 retry、fixture 缺字段 |
| 代码质量 | 异常路径处理充分 | F3: 成功路径缺日志 |

Agent 在**外显行为**层面的发现质量更高（GRADE_PROMPT 未使用、retry 不一致、fixture 缺字段），自评在**结构分析**层面的判断更准（条件边时序分析、约束链结构）。两评无冲突，互补性强。

---

## 行动项

| 优先级 | 行动 | 关联问题 | 状态 |
|--------|------|---------|------|
| P0 | 为内联 prompt 补充跨语言指导语义 | F1 | 已修复 |
| P0 | 移除未使用的 GRADE_PROMPT 导出，保留常量作为参考 | F1 | 已修复 |
| P1 | 为 grade_documents_node 补充成功路径日志 | F3 | 已修复 |
| P2 | 补充 GraphContext.max_rewrite_count 说明注释 | F2 | 已修复 |
| P2 | 补全测试 fixture 中 rewrite_count/max_rewrite_count 字段 | F5 | 已修复 |
| P3 | 修复 test_empty_question 不可达断言 | F6 | 已修复 |
| P4 | 添加 rewrite_node 关于 retry 不一致的设计注释 | F4 | 保留 |
| P5 | 考虑统一 conftest.py 中的 _make_state 定义 | F7 | 后续 |
| P5 | 补充完整重写循环的集成测试 | F9 | 后续 |

---

## 评级

| 评价对象 | 自评 | Agent 评 | 综合 |
|----------|------|----------|------|
| 设计文档 | A | A- | **A-**（F1 设计蓝图与实现偏离降低评级） |
| 代码 | A- | B+ | **A-**（F1 跨语言指导缺失严重但仅影响 prompt 内容，逻辑覆盖完整；F3/F5 不影响正确性） |
| 技术文档 | A | A | **A**（触发点选取准、约束链结构创新内容深度足够，无事实错误） |
