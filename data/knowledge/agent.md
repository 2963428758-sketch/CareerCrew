# Agent 与多智能体

Agent 是能感知、决策、调用工具的智能体。ReAct 循环是经典范式：思考-行动-观察。

## 手写 ReAct
手写 ReAct 循环可见可控：组装上下文 -> 调 LLM(带工具) -> 判断 tool_call -> 执行工具 -> 结果回喂 -> 再循环。不依赖 create_react_agent 黑盒，工具推理过程可 trace。

## LangGraph 编排
LangGraph 用状态机编排多 Agent，supervisor 按阶段路由到专职 agent，支持 HITL interrupt（人工闸门）、checkpointer（thread 级状态持久化）。Hybrid 架构：LangGraph 管编排，agent 节点内手写 ReAct 管工具推理。

## 三层记忆
仿 Hermes 的三层记忆：短期（Context Window）/ 情景（append-only JSONL + parentId 树）/ 长期（User Model 画像）。append-only 树保证历史可完整回放，是轨迹级评估的基础。
