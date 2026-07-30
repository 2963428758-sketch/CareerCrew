## 2. 核心特点

### 多智能体协同 (Multi-Agent Collaboration)
"职业顾问团队"由 5 个专职 agent 构成，由 LangGraph supervisor 按求职阶段路由调度：

| Agent | 职责 | 典型工具 |
|-------|------|---------|
| **职位匹配官** (job_matcher) | 搜新 JD、JD-画像匹配打分、命中入库 | mcp-jobs、rag_query |
| **简历顾问** (resume_advisor) | 按 JD 定制简历、匹配度评估 | rag_query（简历范本）、profile_update |
| **面试官** (interviewer) | 出题、模拟问答、评分、记录面经 | rag_query（面经/八股）、memory_write |
| **薪资谈判师** (salary_negotiator) | 薪资数据检索、谈薪策略与话术 | rag_query（薪资数据）、memory_write |
| **职业规划师** (career_planner) | 建能力画像、定目标公司池、阶段规划 | profile_update、memory_search |

支持**多 agent 会诊**（高级方向）：同一问题路由给多个 agent 并行给意见再综合。

### Hybrid Agent 架构 (LangGraph 编排 + 手写 ReAct 内核)
- **LangGraph supervisor** 管编排：按求职阶段路由到对应 agent、HITL interrupt、checkpointer(SQLite) 做短期 thread 状态持久化。
- **agent 节点内手写 ReAct** 管工具推理：可见的 `while` 循环（组装上下文 -> 调模型 -> 判断有无工具调用 -> 执行工具 -> 结果回喂 -> 再循环），不依赖 `create_react_agent` 之类黑盒抽象。
- **分工必然性**：LangGraph 擅长状态机与中断，手写循环擅长工具推理细节与可控性，两者各取所长。

### 三层记忆系统 (3-Layer Memory，仿 Hermes)
| 层级 | 实现 | 用途 |
|------|------|------|
| **短期** (Short-term) | Context Window | 当前对话轮上下文 |
| **情景** (Episodic) | Session Transcript：append-only JSONL，每条带 `id`+`parentId`，会话存成树，从叶子回溯到根 = 上下文；+ Milvus 向量 | 面试/投递/offer 等事件记忆，可检索可回溯 |
| **长期** (Long-term) | User Model：能力画像 / 目标公司池 / 偏好，结构化 | 跨会话用户画像 |

**append-only 树的红利**：会话是只增不改的树，任何历史轨迹可完整回放——这是轨迹级评估（黄金轨迹回放）的基础。

### RAG 后端复用 + Milvus 可插拔
- **复用** `F:\agent_develop\MODULAR-RAG-MCP-SERVER`：Hybrid 检索（BM25 + Dense + RRF）+ 两段式 Rerank + MCP 暴露；复用 `llm_factory` / `trace` / `evaluator`。
- **扩展**：给 MODULAR-RAG 的 `BaseVectorStore` 抽象基类加 **Milvus 后端**（与 Chroma 并存，配置切换）；本地用 **milvus-lite**（嵌入式零外部服务），Docker 演示用完整 Milvus。
- **知识库**：大模型八股 + 真实面试题、算法岗面经、JD 库（mcp-jobs 沉淀）、公司/薪资公开数据、简历范本。RAG 知识库与记忆向量共用 Milvus（collection 隔离）。

### Function calling 统一工具层
- **统一工具注册表**：MCP 工具（mcp-jobs / Google MCP）+ 内部函数（`memory_search` / `profile_update` / `rag_query` 等）都注册成带 JSON schema 的 tool，agent 用同一接口调用。
- **风险分级**：高风险工具标 `requires_confirmation`，触发 LangGraph interrupt 走 HITL。

### HITL 人工闸门 (Human-in-the-Loop)
求职是高 stakes 决策，默认 HITL：
- **必确认**：投递 / 打招呼 / 接 offer / 谈薪话术（LangGraph interrupt）。
- **可自动化**：搜职位 / 出题 / 出草稿等低风险操作。
- 高级方向：**Delegate 三级授权**（只读草稿 -> 代发待确认 -> 主动执行）细化闸门粒度。

### 求职周期工作流闭环
意向 -> 规划师建画像+目标公司池 -> 匹配官搜新 JD -> 命中 -> 简历顾问定制 -> 面试官模拟+记录 -> 谈判师准备策略 -> HITL 确认投递 -> 跟踪 -> 复盘写入记忆 -> 循环。一个完整的、可 dogfood 的求职陪跑闭环。

### 全链路可观测 + 评估闭环
- **可观测性**：复用 MODULAR-RAG 全链路 trace（JSON Lines）+ Streamlit 基础 Dashboard（系统总览 / 数据浏览 / 追踪查看）。不依赖 LangSmith。
- **评估**：答案级（简历匹配度 / 面试题质量，复用 Ragas）+ 业务级（投递->面试转化率、面试通过率、拿 offer dogfood）。高级方向补轨迹级评估。

### 本地优先 (Local-First)
- LLM 可插拔复用 `llm_factory`（Azure/OpenAI/Ollama/DeepSeek）。
- 向量库 Milvus Lite 嵌入式，Chroma 兜底。
- checkpointer SQLite，情景记忆 JSONL，User Model JSON。
- **零外部服务依赖**即可跑通 MVP。

---
