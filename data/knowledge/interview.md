# 大模型面试题

## RAG 相关
Q: RAG 怎么减少幻觉？
A: 检索真实知识库作为上下文，让生成有据可依，减少模型编造。叠加 rerank 提升相关性。

Q: Hybrid 检索为什么比纯 dense 好？
A: dense 擅长语义匹配，sparse 擅长关键词匹配，两路 RRF 融合兼顾两者，提升召回覆盖。

Q: BGE-M3 三路输出怎么用？
A: dense 做语义召回，sparse 做关键词召回（免 BM25），colbert 做 token 级 late interaction（细粒度匹配，代价高）。

## Agent 相关
Q: 为什么手写 ReAct 而不用 create_react_agent？
A: 手写循环可见可控，工具推理过程全链路 trace 可回放，便于调试和评估，不被黑盒约束。

Q: LangGraph 的 checkpointer 存什么？
A: thread 级状态（当前阶段、对话、待确认动作），进程重启可恢复。默认 SQLite。

Q: append-only 记忆树有什么用？
A: 会话只增不改，任何历史轨迹可完整回放，是轨迹级评估（黄金回放）的物理基础。
