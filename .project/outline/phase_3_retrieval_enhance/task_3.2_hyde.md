## Task 3.2 HyDE 检索器（Hypothetical Document Embeddings）

### 任务目标
实现 HyDE 检索策略——先用 LLM 生成假设性答案文档，再将该文档 embedding 用于检索，缩小用户查询与文档库之间的语义鸿沟，提升概念性、抽象问题的检索效果。

### 涉及文件
- `src/retrieval/hyde.py`
- `src/retrieval/prompts.py`（HyDE 专用 Prompt）

### 面试级知识点
- **HyDE 的核心创新**：传统检索将用户查询直接 embedding，但查询通常是简短的问句，而知识库中的文档是陈述性的长文本——两者在向量空间中的分布不一致（"跨域"问题）。HyDE 先用 LLM 生成一段"假设的答案文档"，这个假设文档的语言风格和结构与真实文档相似，其 embedding 在向量空间中更接近相关文档的 embedding，从而提升检索精度。
- **HyDE 为何有效**：query-to-doc 是跨域检索，而 doc-to-doc 是同域检索——后者 embedding 模型训练数据中更常见，相似度计算更可靠。
- **HyDE 的适用场景**：概念性问题（"什么是 Agent？"）、解释性问题（"Chain 和 Agent 有什么区别？"）效果显著；事实性问题（"某某函数的参数是什么？"）效果有限，因为假设文档可能产生幻觉。

### 生产级注意事项
- **HyDE 的额外成本与延迟**：每次检索多调用一次 LLM 生成假设文档，成本和延迟翻倍。因此需在评估中量化收益是否值得，或仅在特定场景启用（如 `doc_grade == "not_relevant"` 后触发）。
- **跨语言 HyDE**：你的场景是"中文提问 + 英文文档"。HyDE 生成的假设文档应该用英文，因为向量库中的文档是英文，用英文假设文档 embedding 更接近真实文档。Prompt 中明确指定："Generate a hypothetical answer in English to the following question."
- **假设文档长度控制**：生成的假设文档不宜过长（建议 200-500 字符），否则 embedding 会稀释关键信息。Prompt 中加入长度约束。
- **Temperature 设置**：HyDE 生成时应使用较低 temperature（0-0.3），确保生成的假设文档稳定、可复现，避免因随机性导致检索结果波动。
- **失败降级**：LLM 生成假设文档失败时（超时、限流），自动降级为直接使用原始查询检索，不阻断主流程。

### 验收标准
- 运行评估脚本，对比 `BaseRetriever`、`MultiQueryRetriever` 和 `HyDERetriever` 在相同数据集上的指标。
- 按问题类型分组统计（概念类 vs 代码类）：验证 HyDE 在概念类问题上提升更明显。
- HyDE 生成的假设文档以英文输出，且长度 ≤ 500 字符。
- 手动测试概念性问题（如"What is the role of memory in LangChain?"），观察检索结果是否更聚焦于 memory 概念介绍而非具体 API。
