## 1. 项目概述

CareerCrew 是一个多智能体"职业顾问团队"系统，**长期陪跑用户整个求职周期**：职位匹配、简历定制、面试模拟、薪资谈判、职业规划。区别于单点工具（只做简历或只做面试），它是一个**有长期记忆、能调用真实招聘平台与工具、带人工闸门**的多 agent 系统。Demo 入口以 CLI 优先（本地优先、轻量、零外部服务依赖），后续叠加 Streamlit 展示页。

### 设计理念 (Design Philosophy)

> **核心定位：教是最好的学（Learning by Teaching）+ 高 stakes 生活决策的多角色协同**
>
> 求职是少数"多角色协同天然成立"的 AI 应用场景：匹配、简历、面试、谈判、规划本就是不同专业分工，每个角色对应一个 agent，技术栈每项选型都有"非它不可"的必然性。同时这是高 stakes 决策——投错简历、接错 offer 代价大，因此"人工闸门 + 长期记忆"不是锦上添花而是底线要求。

本项目面向**大模型应用 / Agent 方向**的求职与面试实战，定位为：

#### 1️⃣ 实战驱动学习 (Learn by Doing)
项目架构本身就是 Agent / 记忆 / 多智能体面试题的"**活体答案**"。将经典面试考点直接融入代码设计，通过动手实践巩固理论：
- 多 Agent 编排（LangGraph supervisor 路由 / HITL interrupt / checkpointer）
- 手写 ReAct 循环（可见的 while 循环，不依赖 agent 黑盒）
- 三层记忆系统（短期 / 情景 append-only 树 / 长期 User Model）
- 向量库可插拔（自建 Milvus 后端，Chroma 兜底）
- Function calling 工具层（MCP 工具 + 内部函数统一注册）
- 自建 RAG（BGE-M3 三合一 + Contextual Chunking + bge-reranker）

#### 2️⃣ 开箱即用与深度扩展并重 (Plug-and-Play & Extensible)
- **开箱即用**：CLI 优先，本地零外部服务（Milvus Lite 嵌入式），`pip install` 即可跑通求职闭环。
- **深度扩展**：MVP 跑通主流程后，高级方向（Hermes 完整记忆 / Loop Engineering / 轨迹级评估 / 自建 MCP）提供清晰升级路径。
- **分层标注**：spec 中每项技术明确标注【MVP 核心】或【高级方向】，避免"把高级内容当必做"。

#### 3️⃣ 配套教学资源 (Comprehensive Learning Materials)
针对每个模块整理：
- **📚 知识点清单**：涉及哪些理论需提前学习（如 ReAct 原理、LangGraph 状态机、Hermes 记忆架构、RRF 融合）
- **❓ 高频面试题**：结合项目代码讲解常见面试问题及参考答案
- **📝 简历撰写建议**：如何把本项目的亮点写进简历，突出技术深度

#### 4️⃣ Dogfood 闭环 (Eat Your Own Dog Food)
知识库现成能自己 dogfood：大模型八股 + 真实面试题 + 算法岗面经 + JD 库 + 简历范本。系统帮用户求职的过程，本身就是在用这些知识库——**拿 offer 即项目验收**。

---
