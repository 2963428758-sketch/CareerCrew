<!-- CareerCrew DEV_SPEC 初稿。基于 prompts/gen_dev_spec.md (v3) 生成，结构参照主流 DEV_SPEC 模板。 -->
# Developer Specification (DEV_SPEC)

> 版本：0.3 - 修订版（LangGraph 1.x 对齐 + HITL 恢复语义 + 数据源/MCP 落地 + 配置同步）

## 目录

- 项目概述
- 核心特点
- 技术选型与架构设计（按 MVP/高级分层）
- 测试方案
- 系统架构与模块设计
- 项目排期
- 可扩展性与未来展望
- 面试考点与简历亮点映射
- 快速开始

---

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
- **开箱即用**：CLI 优先，本地服务零依赖（Milvus Lite 嵌入式），LLM/Rerank 走硅基流动 API，`pip install` 即可跑通求职闭环。
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

### 自建 RAG 流水线（最新技术）
- **Embedding：BGE-M3 三合一**：一个模型同时输出 dense + sparse + ColBERT 多向量，中文 100+ 语言，8192 token，MIT 许可，本地 FlagEmbedding 可跑--比"分离的 BM25 + 单独 embedding"更优雅，稀疏路免额外倒排索引。
- **Chunking：RecursiveCharacterTextSplitter + Contextual Chunking**：Markdown 感知切分 + Anthropic Contextual Retrieval（LLM 给每块生成 50-100 token 上下文前置，再做 embedding/sparse 索引），减少 49% 检索失败，叠加 rerank 降 67%。
- **检索：Hybrid + RRF**：BGE-M3 dense + BGE-M3 sparse 两路 RRF 融合，Milvus 原生支持 BGE-M3 混合检索。
- **Rerank：硅基流动 rerank API**（托管 bge-reranker-v2-m3）：cross-encoder 中文重排，低频走 API。
- **向量库：Milvus Lite**（原生 BGE-M3 hybrid、嵌入式零外部服务）+ Chroma 兜底，配置切换。
- **文档加载：多格式**：MarkItDown 统一加载 PDF/Word/Markdown，转 Markdown 后走 Markdown 感知切分。
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
- **可观测性**：自建全链路 trace（JSON Lines，TraceContext 机制）+ Streamlit 基础 Dashboard（系统总览 / 数据浏览 / 追踪查看）。不依赖 LangSmith。
- **评估**：答案级（简历匹配度 / 面试题质量，集成 Ragas）+ 业务级（投递->面试转化率、面试通过率、拿 offer dogfood）。高级方向补轨迹级评估。

### 本地优先 (Local-First)
- LLM 走硅基流动（OpenAI 兼容 API）：`langchain init_chat_model` + 薄 `create_llm(settings)` 适配，`base_url` 配置切换。
- Embedding 本地 BGE-M3（dense+sparse+colbert，FlagEmbedding）；Rerank 走硅基流动 rerank API。
- 向量库 Milvus Lite 嵌入式，Chroma 兜底。
- checkpointer SQLite，情景记忆 JSONL，User Model JSON。
- 本地服务零依赖（Milvus Lite/SQLite/JSONL）；LLM/Rerank 走 API。

---

## 3. 技术选型与架构设计

> **分层约定**：每节标注【MVP 核心】（必须实现，A-L 阶段）或【高级方向】（理解/能讲/后期实现，挑 1-2 亮点放 M-N 阶段）。高级内容**不阻塞主流程**。

### 3.1 多 Agent 编排（LangGraph supervisor）【MVP 核心】

**目标：** 用 LangGraph 搭建 supervisor 编排架构，5 个 agent 节点按求职阶段路由，支持 HITL interrupt 与短期状态持久化。

#### 3.1.1 设计理念
- **Supervisor 路由模式**：supervisor 节点接收用户意图与当前阶段，决定路由到哪个 agent（或多个 agent 会诊）。agent 执行完毕后回到 supervisor 决定下一步。
- **状态机显式化**：求职阶段（意向 / 规划 / 匹配 / 简历 / 面试 / 谈判 / 投递 / 跟踪 / 复盘）作为状态机的显式状态，路由逻辑可解释、可测试。
- **HITL 原生**：LangGraph 的 `interrupt` 机制天然支持"暂停等人工确认后恢复"，契合高 stakes 闸门需求。
- **checkpointer 持久化**：thread 级短期状态（当前阶段、最近几轮对话、待确认动作）用 SQLite checkpointer 持久化，进程重启可恢复。

#### 3.1.2 supervisor 与 agent 节点分工
- **supervisor 节点**：不直接调工具，只做"读状态 -> 判断阶段 -> 路由到 agent / 触发 HITL / 结束"。
- **agent 节点**：内部跑手写 ReAct 循环（见 3.2），可调工具，产出结果后返回 supervisor。
- **HITL 节点**：supervisor 遇 `requires_confirmation` 动作时，`interrupt` 暂停，等待人工 yes/no，恢复后继续。

#### 3.1.3 状态结构（Thread State）
```python
# careercrew_core/state/thread_state.py（示意）
class CareerCrewState(TypedDict):
    thread_id: str
    user_id: str
    stage: str                      # 求职阶段：intent|planning|match|resume|interview|negotiate|apply|track|review
    user_intent: str                # 用户当前意图
    messages: list                  # 短期对话（Context Window）
    pending_action: dict | None     # 待确认动作（HITL）
    agent_outputs: dict             # 各 agent 产出（候选 JD / 简历草稿 / 面试记录 等）
    target_companies: list[str]     # 目标公司池
    # ... 其余由各阶段按需扩展
```

#### 3.1.4 checkpointer 选型
- **默认：SQLite**（`data/db/checkpointer.db`），本地零依赖，WAL 模式支持并发。
- **可替换**：LangGraph checkpointer 抽象支持后续换 Postgres（分布式场景）。

#### 3.1.5 多 agent 会诊【高级方向】
- 同一问题（如"这个 offer 要不要接"）路由给多个 agent（谈判师 + 规划师 + 面试官）并行给意见，supervisor 综合后输出。
- 实现上用 LangGraph 的并行 fan-out + join。

#### 3.1.6 LangGraph 版本约定（1.x）【MVP 核心】

> 2026-08-01 实测环境（conda env `careercrew`）：langgraph 1.2.10 / langchain 1.3.14 / langchain-core 1.5.2 / langchain-openai 1.4.1 / pymilvus 3.0.1。

- **统一按 LangGraph 1.x API 实现**（pyproject 下限已改为 `langgraph>=1.2.0`）。spec 中所有图 / 中断 / 检查点描述以 1.x 为准，0.2 时代写法不再使用：
  - `interrupt()` 是节点内函数（`langgraph.types.interrupt`），恢复用 `Command(resume=...)`（`langgraph.types.Command`）；不用"抛 Interrupt 信号给 supervisor"的旧写法。
  - checkpointer 从 `langgraph.checkpoint.sqlite` 导入（`SqliteSaver`），`StateGraph.compile(checkpointer=...)`。
  - 不依赖 `create_react_agent`（手写 ReAct 本身就是本项目卖点）。
- **版本锁定原则**：MVP 阶段 pyproject 用兼容范围安装，但**以本表实测版本为准写代码**；升级/新增依赖前先验证 API 兼容，避免按旧文档 API 落码。
- **LLM / Rerank 模型名已实测可用**（2026-08-01，硅基流动 `/v1/models`）：`deepseek-ai/DeepSeek-V4-Flash`、`BAAI/bge-m3`、`BAAI/bge-reranker-v2-m3` 均存在。

---

### 3.2 Agent 内核（手写 ReAct）【MVP 核心 - 基础版】+【高级方向 - 高级特性】

**目标：** 在 LangGraph agent 节点内套一个**可见的** ReAct 工具循环，不依赖 agent 抽象黑盒，保证工具推理过程透明、可控、可测试。

#### 3.2.1 基础版 ReAct 循环【MVP 核心】
显式 `while` 循环，每一步都可见：

```
组装上下文（短期对话 + 按需检索的记忆 + 工具 schema）
    │
    ▼
┌─────────────────────────────────────────┐
│  while 未达到结束条件:                    │
│    1. 调 LLM（带工具 schema）             │
│    2. 解析返回:                            │
│       - 有 tool_call -> 执行工具 -> 结果回喂│
│       - 无 tool_call -> 视为最终答案, break│
│    3. 安全检查: 轮次上限 / 异常 / 中断      │
└─────────────────────────────────────────┘
    │
    ▼
返回 agent 产出
```

**关键设计**：
- **工具调用判定**：解析 LLM 返回的 `tool_calls` 字段（统一 function calling 格式），而非依赖正则解析 "Action: xxx"。
- **轮次上限**：防止死循环，默认 `max_iterations=10`，超限抛可读错误。
- **上下文组装**：每轮重新组装（短期对话 + 主动检索的记忆 + 已执行工具结果），不靠隐式状态。
- **可观测**：每轮迭代记录到 trace（thought / tool_call / tool_result），供 Dashboard 回放。

#### 3.2.2 高级特性【高级方向】
- **工具并行/串行策略**：工具声明 `parallel_safe` 配置，一轮内多个独立工具并行执行，有依赖的串行。
- **运行中插话 (steering)**：循环执行中允许用户插入指令调整方向。
- **收尾追问 (follow-up)**：答案给出后主动追问澄清，而非一次性结束。
- **随时中断 (abort)**：长循环可被外部中断，已执行步骤不丢失（落到情景记忆）。

---

### 3.3 记忆系统（3 层基础版）【MVP 核心】+【高级方向 - Hermes 完整版】

**目标：** 仿 Hermes 设计三层记忆，MVP 实现基础版（短期 / 情景 append-only 树 / 长期 User Model），完整版（Skill 库 / 反思 / 双通道 / compaction 完整策略）放高级方向。

#### 3.3.1 短期记忆【MVP 核心】
- **实现**：Context Window，即 LangGraph thread state 中的 `messages`。
- **管理**：由 compaction 基础版（见 3.3.5）控制长度，超阈值触发压缩。

#### 3.3.2 情景记忆（Episodic）【MVP 核心】
**核心数据结构：append-only JSONL + parentId 树**

```jsonl
{"id":"e_001","parentId":null,"type":"session_start","ts":"...","content":"..."}
{"id":"e_002","parentId":"e_001","type":"interview_qa","content":{"q":"...","a":"...","score":8}}
{"id":"e_003","parentId":"e_002","type":"job_match","content":{"jd":"...","score":0.85}}
{"id":"e_004","parentId":"e_003","type":"application","content":{"company":"...","status":"submitted"}}
```

- **append-only**：只增不改，保证可完整回放。
- **parentId 树**：每条记录指向父节点，会话构成树；从任意叶子回溯到根 = 该上下文的完整历史。
- **向量索引**：每条（或按事件聚合后）写一份 embedding 到 Milvus（collection: `careercrew_episodic`），支持语义检索。
- **存储**：`data/transcripts/{user_id}/{thread_id}.jsonl`。

**上下文重建**：给定当前叶子节点 id，沿 `parentId` 链回溯到根，按时间序拼接即为上下文。这是 ReAct 循环"组装上下文"的重要输入。

#### 3.3.3 长期记忆（User Model）【MVP 核心】
结构化的跨会话用户画像：

```python
# data/user_model.json（示意）
{
  "user_id": "u_001",
  "profile": {
    "skills": ["Python", "LangGraph", "RAG", ...],
    "level": "中级",
    "direction": "大模型应用/Agent"
  },
  "target_companies": ["...", "..."],
  "preferences": {"salary_min": 30, "city": ["北京","上海"], ...},
  "interview_mastery": {"RAG": 0.8, "Agent": 0.6}  # 面经掌握度（高级方向丰富化）
}
```

- **读写**：通过 `profile_update` 工具结构化更新（非自由文本，字段约束）。
- **用途**：规划师建画像、匹配官过滤、谈判师定底线。

#### 3.3.4 基础写入触发点【MVP 核心】
关键事件后自动写情景记忆：
- 面试结束 -> 写 `interview_qa` + 评分
- 投递后 -> 写 `application`
- 拿 offer -> 写 `offer`
- 匹配命中 -> 写 `job_match`

#### 3.3.5 Compaction 基础版【MVP 核心】
- **触发**：token 占比达阈值（**优先用模型真实 usage**，不用字符数/4 估算）。
- **策略（基础版）**：保留区（最近 ~20K tokens 原封不动）+ 压缩区（分块总结 -> 合并 -> 写 JSONL compaction 条目，带 `firstKeptEntryId` 标记保留区起点）。

#### 3.3.6 记忆事件契约【MVP 核心】

情景记忆与 trace 共用的最小事件契约（C1 落地字段，L2 业务级评估 / L3 trace 消费，避免阶段间返工）：
- **事件类型**（`MemoryEntry.type` 枚举）：`job_match` / `interview_qa` / `application` / `offer` / `salary_talk` / `review` / `profile_update` / `compaction`。
- **通用字段**：`id` / `parentId` / `type` / `ts` / `content`（摘要文本）/ `metadata`（结构化）。
- **关键事件 metadata 字段**：
  - `job_match`：`job_id` / `title` / `company` / `match_score`
  - `interview_qa`：`company` / `position` / `question` / `answer_summary` / `score` / `feedback`
  - `application`：`job_id` / `company` / `position` / `status`
  - `offer`：`company` / `position` / `package_summary` / `decision`
- **trace 事件**（L3）：`trace_id` / `span_id` / `parent_span_id` / `ts` / `type`（`agent_loop` / `tool_call` / `tool_result` / `hitl` / `memory_op`）/ `payload`。
- 契约先在 `careercrew_core/memory/types.py` 定死并由单测锁定（C1 验收标准），后续阶段只增不改。

#### 3.3.7 高级方向【高级方向】
- **Hermes 完整版**：Skill Library（先加载精简描述，命中才加载全文）/ User Model 丰富化 / 反思自进化循环（Skill 自我改进、面经掌握度图谱）/ 记忆双通道检索（系统每轮自动检索 + Agent 主动 `memory_search`）。
- **compaction 完整策略**：token 占比触发 + 保留区 + 压缩区 + **Pre-compaction Memory Flush**（压缩前先静默跑一轮把重要信息写进长期记忆再压缩，防丢关键信息）。
- **记忆双通道**：系统级自动注入（before_model hook 每轮检索相关记忆）+ Agent 级主动检索（`memory_search` 工具）。

---

### 3.4 Function calling 与工具层【MVP 核心】

**目标：** 统一工具注册表，MCP 工具与内部函数同一接口，agent 无感调用；高风险工具触发 HITL。

#### 3.4.1 统一工具注册表
所有工具（不论来源）注册成统一 schema：

```python
# 工具描述（统一格式）
{
  "name": "rag_query",
  "description": "检索知识库（八股/面经/JD/简历范本）",
  "schema": {"type":"object","properties":{"query":{"type":"string"},"top_k":{"type":"integer"}},"required":["query"]},
  "source": "internal",          # internal | mcp
  "requires_confirmation": false, # 高风险标 true
  "parallel_safe": true
}
```

- **MCP 工具**：mcp-jobs（职位检索）、Google MCP（搜索）。通过 MCP client 动态发现并注册。
- **内部函数**：`memory_search` / `profile_update` / `rag_query`（封装自建 RAG 检索）/ `memory_write` 等。

#### 3.4.2 工具执行
- **基础并行/串行**：同一轮内 `parallel_safe=true` 的工具并行执行；有依赖的串行。
- **结果回喂**：工具结果按 function calling 规范回喂给下一轮 LLM。
- **高风险拦截**：执行前检查 `requires_confirmation`，若为 true 则不执行工具，调用节点内 `interrupt()` 挂起图走 HITL（恢复语义见 §3.8.2）。

#### 3.4.3 RAG 工具化
自建 RAG 检索能力被封装成 `rag_query` 内部工具暴露给 agent，agent 按需调用检索知识库（见 3.7）。

---

### 3.5 向量库可插拔（Milvus）【MVP 核心】

**目标：** 自建 `BaseVectorStore` 抽象基类 + Milvus 后端（与 Chroma 并存，配置切换）；本地用 milvus-lite 嵌入式零外部服务。

#### 3.5.1 Milvus 后端实现
- **位置**：`careercrew_ai/vector_store/milvus_store.py`（CareerCrew 自有，非外部贡献）。
- **实现 `BaseVectorStore` 接口**：`upsert(records)` / `query(vector, top_k, filters)` / `delete_by_metadata(filter)` / `get_by_ids` 等契约方法。
- **支持 Dense + Sparse**：Milvus 原生支持 BGE-M3 混合检索（Dense 向量 + Sparse token weights），与 BGE-M3 三路输出契合。

#### 3.5.2 部署模式
| 模式 | 适用场景 | 说明 |
|------|---------|------|
| **milvus-lite** | 本地开发、MVP | 嵌入式，`pip install milvus-lite` 即用，零外部服务；**Windows 需单独装 wheel（见 README），装不上时 D2 默认切 `chroma` 兜底** |
| **milvus (Docker)** | 演示、规模扩展 | 完整 Milvus 服务，docker-compose 启动 |
| **chroma** | 兜底 | 自建 ChromaStore 实现，配置切换 |

#### 3.5.3 配置切换
`settings.yaml` 中 `vector_store.backend: milvus_lite | milvus_docker | chroma`，工厂路由，零代码切换。

#### 3.5.4 Collection 隔离
RAG 知识库与情景记忆向量共用 Milvus 实例，但 collection 隔离：
- `careercrew_kb`：知识库（八股/面经/JD/简历范本）
- `careercrew_episodic`：情景记忆向量

---

### 3.6 MCP 工具层【MVP 核心 - 现成 MCP】+【高级方向 - 自建 MCP】

**目标：** 接入现成 MCP 工具跑通 MVP；自建求职者端 MCP 放后期。

#### 3.6.1 现成 MCP 接入【MVP 核心 - mock 先行】
- **策略：mock 先行，真实 MCP 可选**。MVP 阶段先落地 mock（`tools/mcp/mock_jobs.py` 提供样例 JD）保证 E3-E4 不依赖外部 server；真实 server 接入不阻塞任何排期任务，接入后由统一注册表自动发现注册。
- **外部 MCP server 清单**（本机均未预装，接入参数 E2 阶段确定）：

  | server | 用途 | 接入方式 | MVP 状态 |
  |--------|------|---------|---------|
  | mcp-jobs | 职位检索（JD 库） | MCP client（stdio 命令或 SSE URL） | mock 兜底，真实可选 |
  | Google MCP | 通用搜索（公司信息/薪资公开数据补充） | MCP client | 可选；未接入时用 rag_query + 手动数据替代 |

- 通过 MCP client 连接，工具自动注册进统一工具注册表；连接失败按 §5.7 降级（工具返回错误信息给 agent，不阻塞主流程）。

#### 3.6.2 投递/进度跟踪 Mock【MVP 核心】
MVP 阶段投递与进度跟踪用 mock（不真实调用招聘平台），保证闭环可跑通。HITL 闸门在 mock 上验证。

#### 3.6.3 自建求职者端 MCP【高级方向】
- 仿 `boss-zhipin-mcp`，用 **Playwright + CDP** 实现。
- 能力：真实投递、进度跟踪、面经采集。
- 暴露为 MCP Server，注册进工具层。

---

### 3.7 自建 RAG 流水线（最新技术）【MVP 核心】

**目标：** 自建完整 RAG 流水线，采用 2024-2026 主流技术（BGE-M3 三合一 + Contextual Chunking + bge-reranker），不依赖外部 RAG 项目。

#### 3.7.1 技术栈分层
| 环节 | 选型 | 实现位置 | 说明 |
|------|------|---------|------|
| Loader | MarkItDown（统一）+ Markdown 直读 | `careercrew_core/rag/loaders/` | PDF/Word/Excel/HTML 转 Markdown；.md 直读；BaseLoader 可插拔 |
| Chunking | RecursiveCharacterTextSplitter + **Contextual Chunking** | `careercrew_core/rag/chunking/` | Markdown 感知切分；每块调 LLM 生成 50-100 token 上下文前置再索引（Anthropic Contextual Retrieval，减 49% 检索失败） |
| Embedding | **BGE-M3**（dense + sparse + ColBERT） | `careercrew_ai/embedding/` | 一模型三路输出，中文 100+ 语言，8192 token，本地 FlagEmbedding；稀疏路免额外 BM25 索引 |
| 检索 | Hybrid（BGE-M3 dense + sparse）+ RRF 融合 | `careercrew_core/rag/retrieval/` | 两路 RRF 融合，Milvus 原生支持 BGE-M3 混合检索 |
| Rerank | **硅基流动 rerank API**（bge-reranker-v2-m3） | `careercrew_ai/reranker/` | cross-encoder 中文重排，低频走 API；可关（None）回退 |
| 向量库 | Milvus Lite + Chroma 兜底 | `careercrew_ai/vector_store/` | 见 3.5 |

#### 3.7.2 设计亮点
- **BGE-M3 三合一 > 分离的 BM25+Embedding**：一次前向同时得 dense/sparse/colbert，稀疏路无需维护倒排索引，与 Milvus 原生混合检索直接对接。
- **Contextual Chunking**：ingestion 阶段用 LLM 给每块生成文档级上下文前置，解决"块脱离上下文难检索"问题；可用 prompt caching 控成本（若 provider 支持）。
- **可插拔**：Embedding/Rerank/VectorStore 均为 `Base*` 抽象 + 工厂，配置切换（如换 OpenAI embedding、Cohere rerank）零代码。

#### 3.7.3 知识库 Ingestion
自建 Ingestion Pipeline 摄取知识库到 Milvus（collection `careercrew_kb`）：
- 大模型八股 + 真实面试题
- 算法岗面经
- JD 库（MVP 由 `mock_jobs` 生成 + 用户手动收集，真实 mcp-jobs 沉淀为增量）
- 公司/薪资公开数据
- 简历范本

流水线：Loader（PDF/Word/Markdown 统一转 Markdown）-> Splitter -> Contextual Chunking（LLM 加上下文）-> BGE-M3 编码（dense+sparse）-> Milvus Upsert。

**MVP 首批知识库（`data/knowledge/`，D4 验收用；先备数据再实现 pipeline）**：

| 类别 | 内容 | 来源 | 许可 / 合规 |
|------|------|------|------------|
| 大模型八股 | 1 份 Markdown（100-300 行常见概念问答） | 自写整理（优先）或开源笔记 | 自写无版权问题；引用开源须注明来源 |
| 真实面试题 | 面试题集 Markdown 1 份 | 自备或开源仓库（标注来源） | 按来源 License |
| 算法面经 | 可选 1 份 | 同上 | 同上 |
| JD 库 | 5-10 条样例 JD | `mock_jobs` 生成 + 用户手动收集 | 招聘公开信息 |
| 简历范本 | 用户自己的简历 1-2 份（脱敏）+ 结构化字段说明 | 用户自备 | 用户自有，勿外传 |
| 公司/薪资数据 | 公开薪资表（可选） | 开源数据集或自备 | 按来源 License |

> 数据源原则：**dogfood 优先用用户自己的材料**（简历 / 面经 / 目标公司），开源材料只作补充；不抓取受版权保护内容。

#### 3.7.4 文档加载（多格式）【MVP 核心】

**目标：** 知识库文档格式多样（PDF 面经、Markdown 八股、Word 简历范本），统一加载为 `Document(text + metadata)` 供后续切分。

**选型：MarkItDown（统一）+ Markdown 直读**
- **Markdown（.md）**：直接读文本，保留标题层级，无需转换。
- **PDF / Word(.docx) / Excel / PPT / HTML**：用 [MarkItDown](https://github.com/microsoft/markitdown)（微软）统一转 Markdown，再走 Markdown 感知切分。一个库覆盖多格式，省去维护多个 parser。
- **回退**：若 MarkItDown 对某 PDF 效果差，可换 PyMuPDF（fitz）做 PDF 文本提取；Word 可换 python-docx。`BaseLoader` 抽象保证可插拔。

**实现位置**：`careercrew_core/rag/loaders/`
- `base_loader.py`：`BaseLoader.load(path) -> Document`（`text` + `metadata:{source_path, doc_type, title}`）
- `markdown_loader.py`：Markdown 直读
- `markitdown_loader.py`：MarkItDown 统一转 PDF/Word/etc.
- 工厂按扩展名路由：`.md` -> MarkdownLoader；`.pdf/.docx/.doc/...` -> MarkItDownLoader

**Document 契约**：`{id, text(markdown), metadata:{source_path, doc_type, title}}`，与下游 Splitter 衔接。

#### 3.7.5 已知检索质量局限与优化方向【已知问题 - 后期优化】

> D 阶段验收用 11 文档 ~319 chunks 知识库做 12 问命中率测试，**9/12 强命中**（rerank score≥0.5）。3 个弱命中（"rerank 重排解决什么问题" / "为什么手写 ReAct 而不用 create_react_agent" / "大模型量化有哪些方法"）**内容在 KB 中存在但未被排到 top**，是检索质量问题，非内容缺口。

**根因**：
- 纯字符递归切分（chunk_size=800）会把"最佳答案"混在较大上下文块里，hybrid + rerank 未能精确切中。
- query 表述与内容表述不完全匹配（如"量化有哪些方法" vs 内容里的"量化方法对比"）。

**优化方向（后期，按性价比排序）**：
1. **更细 / 语义化 chunking**：按 Q&A 对、按主题段落切（SemanticChunker），或减小 chunk_size；让"答案"成独立 chunk。
2. **Agentic RAG（M4 阶段）**：query 改写 / 多查询分解 + `rrf_fuse`（已就绪）融合；Self-RAG / CRAG 检索自纠正（M5）。
3. **Late Chunking / ColBERT 多向量（M7 阶段）**：BGE-M3 colbert 模式 token 级 late interaction，提升细粒度匹配。
4. **参数调优**：rerank `top_m`、`chunk_size/overlap`、RRF `k`。

> 验收基线：12 问 9/12 强命中（75%）；优化目标 ≥ 11/12。优化在 M 阶段做，不阻塞 MVP 主流程。

---

### 3.8 HITL 闸门【MVP 核心 - 基础】+【高级方向 - Delegate 三级授权】

**目标：** 高 stakes 决策必人工确认；高级方向细化授权粒度。

#### 3.8.1 基础 HITL【MVP 核心】
- **机制**：LangGraph `interrupt`。工具标 `requires_confirmation=true` 时，supervisor 暂停图执行，等待人工确认（CLI 输入 yes/no / 修改）后恢复。
- **必确认动作**：
  - 投递简历（`submit_application`）
  - 打招呼（`send_greeting`）
  - 接 offer（`accept_offer`）
  - 谈薪话术（`salary_talk_script`）
- **恢复**：人工可确认 / 拒绝 / 修改后确认，结果写回 state 与情景记忆。

#### 3.8.2 interrupt 恢复语义【MVP 核心】

> ReAct 循环内触发 HITL 的实现约束（B2 / K2 落地，langgraph 1.x）：

- **挂起**：ReAct 循环的工具执行器发现 `requires_confirmation=true` 时**不执行工具**，调用节点内 `interrupt()` 挂起整个图，payload = 待确认动作（工具名 + 参数 + 风险说明）。CLI 通过 `stream_mode="updates"` 收到 `__interrupt__` 事件后渲染确认 UI；**等待输入期间图处于挂起状态，不阻塞线程**。
- **恢复**：用户输入 yes / no / 修改后，以 `Command(resume=decision)` 继续执行，图从 interrupt 点恢复（checkpointer 已保存节点状态）。
- **决策分支**：
  - `yes`：执行原工具，结果回喂 ReAct 循环继续。
  - `no`：工具返回"用户已拒绝"结果，agent 据此调整或终止当前动作。
  - `修改`：以修改后的参数执行工具，结果回喂。
- **上下文重建约束（关键）**：ReAct 循环的中间状态（已执行工具结果 / 循环轮次）必须可从 `CareerCrewState`（messages / agent_outputs）重建，**不得只存进程内存**——否则进程重启或图恢复时循环上下文丢失。
- **进程重启**：中断后进程退出，重新启动后通过 SQLite checkpointer 恢复到上次 interrupt 点继续。

#### 3.8.3 Delegate 三级授权【高级方向】
| 级别 | 风险 | 行为 | 示例 |
|------|------|------|------|
| **只读草稿** | 高 | 必确认 | 投递 / 接 offer / 谈薪话术 |
| **代发待确认** | 中 | 执行后待确认 | 打招呼、跟进 |
| **主动执行** | 低 | 自动 | 搜职位 / 出题 / 出草稿 |

---

### 3.9 求职周期工作流【MVP 核心】

**目标：** 实现完整求职陪跑闭环，可 dogfood。

```
意向 (intent)
   │
   ▼
规划师：建能力画像 + 目标公司池 (planning)
   │
   ▼
匹配官：搜新 JD -> JD-画像匹配打分 -> 命中入库 (match)
   │  命中
   ▼
简历顾问：按 JD 定制简历 + 匹配度评估 (resume)
   │
   ▼
面试官：模拟出题 -> 问答 -> 评分 -> 记录面经 (interview)
   │
   ▼
谈判师：薪资数据检索 -> 谈薪策略与话术 (negotiate)
   │
   ▼
HITL 确认投递 (apply) ── interrupt
   │
   ▼
跟踪进度 (track) ── mock / 自建 MCP
   │
   ▼
复盘 -> 写入情景记忆 (review)
   │
   └──> 循环回 match（持续陪跑）
```

每个阶段由 supervisor 路由到对应 agent，阶段切换可由用户驱动或 agent 产出触发。

---

### 3.10 评估体系【MVP 核心 - 答案级 + 业务级】+【高级方向 - 轨迹级】

**目标：** 答案级评估单次产出质量，业务级评估 dogfood 效果；高级方向补轨迹级。

#### 3.10.1 答案级评估【MVP 核心】
- **简历匹配度**：定制简历与 JD 的匹配分数（集成 Ragas + 自定义指标）。
- **面试题质量**：出题相关性、难度合理性（Ragas Answer Relevancy + 自定义）。
- 自建 `CompositeEvaluator` + golden test set。

#### 3.10.2 业务级评估【MVP 核心】
- **投递 -> 面试转化率**
- **面试通过率**
- **拿 offer（dogfood 终极指标）**
- 数据来源：情景记忆中的 `application` / `interview_qa` / `offer` 事件统计。

#### 3.10.3 轨迹级评估【高级方向】
- 路由准确率 / 工具调用合理性（precision/recall）/ 记忆利用率（`memory_hit_rate`）/ ReAct 效率 / Grounding / HITL 触发正确性 / 压缩无损性。
- **LLM-as-judge** + **黄金轨迹回放**（append-only 树的红利：历史轨迹可完整回放比对）。

---

### 3.11 可观测性与 Dashboard【MVP 核心 - 基础】

**目标：** 自建全链路 trace + Streamlit 基础 Dashboard，不依赖 LangSmith。

#### 3.11.1 全链路 Trace【MVP 核心】
- 自建 `TraceContext` + JSON Lines 日志（`logs/traces.jsonl`）。
- CareerCrew 新增打点：supervisor 路由决策、agent ReAct 每轮（thought/tool_call/tool_result）、HITL 触发与结果、记忆读写、compaction。
- trace_type：`query` / `ingestion` / `agent_loop` / `hitl` / `memory_op` / `compaction`。

#### 3.11.2 Streamlit Dashboard【MVP 核心】
基础三页面（CareerCrew MVP 自建并裁剪）：
- **系统总览**：agent 配置、记忆统计、当前求职阶段。
- **数据浏览**：User Model、情景记忆树浏览、候选 JD / 简历草稿。
- **追踪查看**：agent ReAct 轨迹回放、HITL 历史、记忆检索命中。

---

### 3.12 分层目录结构【MVP 核心】

四层文件夹组织，单向依赖（core 不碰渲染，UI 订阅 core 产出）：

| 层 | 包名 | 职责 |
|----|------|------|
| AI 层 | `careercrew_ai` | LLM 适配(init_chat_model)/embedding(BGE-M3)/reranker/vector_store；手写 ReAct 内核；agent prompts |
| 核心层 | `careercrew_core` | LangGraph supervisor + 5 agent 节点 + 记忆 + 工具注册表 + state |
| 产品层 | `careercrew_cli` | 求职周期工作流编排 + HITL 闸门 + CLI 入口 |
| UI 层 | `careercrew_ui` | CLI 渲染 + Streamlit Dashboard |

> 详细目录树见 5.2。

---

### 3.13 高级方向汇总【高级方向 - 理解/能讲/后期实现】

> 以下为高级方向清单，**不是必做**。M-N 阶段挑 1-2 个亮点实现，其余做到"理解 + 能讲"即可。

- **Hermes 完整版记忆**：Skill Library / User Model 丰富化 / 反思自进化循环 / 记忆双通道检索。
- **compaction 完整策略**：token 占比触发（用模型真实 usage）+ 保留区 + 压缩区 + **Pre-compaction Memory Flush**。
- **Loop Engineering 视角**：求职闭环建模为七步 `Goal->Task->Loop->Execute->Evidence->Asset->Govern`；三角色对位（规划师=Planner / 执行 agent=Developer / 面试官+评估=Reviewer，建设性对抗）；原则"Design the loop, not the perfect prompt"；human-in-loop 默认 HITL。
- **手写 ReAct 高级**：工具并行/串行策略（`parallel_safe`）、运行中插话(steering)、收尾追问(follow-up)、随时中断(abort)。
- **Agentic RAG**：query router（路由到 KB/web/记忆）、query decomposition（多跳问题分解为子查询）、multi-step 检索；与多 agent 架构天然契合。
- **检索自纠正（Self-RAG / CRAG）**：检索评估器打分，质量差则触发重试/查询改写/web 回退；提升 Grounding。
- **层级/图 RAG（RAPTOR / LightRAG）**：递归抽象树或轻量知识图，用于面经跨文档关联与全局性问题。
- **Late Chunking / ColBERT 多向量**：BGE-M3 的 colbert 模式做 token 级 late interaction，提升细粒度匹配。
- **轨迹级评估**：路由准确率 / 工具调用 precision/recall / `memory_hit_rate` / ReAct 效率 / Grounding / HITL 触发正确性 / 压缩无损性；LLM-as-judge + 黄金轨迹回放。
- **Delegate 三级授权**：只读草稿 -> 代发待确认 -> 主动执行。
- **Hooks 统一接口**：`before_tool_call`(HITL闸门) / `before_model`(记忆注入、context改写) / `before_compaction`(flush) / `after_compaction`。
- **事件驱动 + 单向依赖**：core 只跑逻辑发事件不碰渲染，UI 订阅事件，一套 core 配 CLI + Dashboard 双前端。
- **自建求职者端 MCP**：仿 boss-zhipin-mcp 的 Playwright+CDP（投递/进度跟踪/面经采集）。

### 3.14 关键设计决策记录（ADR）

> 记录"为什么这么选"，便于面试讲解与后续复盘。每条含：决策点、备选、选定、理由。

| # | 决策点 | 备选 | 选定 | 理由 |
|---|--------|------|------|------|
| ADR-1 | Agent 架构 | 纯 LangGraph / AutoGen / CrewAI / Hybrid | **Hybrid（LangGraph 编排 + 手写 ReAct）** | LangGraph 擅长状态机/HITL/checkpointer；手写 ReAct 让工具推理可见可控可测试。AutoGen/CrewAI 偏黑盒，可控性与可观测性弱。 |
| ADR-2 | RAG 实现 | 复用 MODULAR-RAG / 自建 | **自建** | 用最新技术（BGE-M3+Contextual Chunking），不被外部项目约束；面试能讲透每个环节。 |
| ADR-3 | Embedding | API dense / 本地 BGE-M3 / OpenAI | **本地 BGE-M3** | 三合一(dense+sparse+colbert)只有本地 FlagEmbedding 能拿；API 只给 dense。高频调用留本地省钱。 |
| ADR-4 | LLM 调用 | 自建 BaseLLM 工厂 / 裸 openai SDK / init_chat_model | **init_chat_model 薄适配** | LangGraph 原生用 ChatOpenAI，自建只是包 SDK 无价值；init_chat_model 是 LangChain 现代工厂，base_url 切 provider。 |
| ADR-5 | LLM 平台 | Azure/OpenAI/Ollama/硅基流动 | **硅基流动** | 国内可访问、OpenAI 兼容、模型多（Qwen/DeepSeek/GLM）、便宜。 |
| ADR-6 | Rerank | 本地 bge-reranker / 硅基流动 API | **硅基流动 API** | 低频（每查询仅 top-30 候选），API 即可，省本地算力。 |
| ADR-7 | 向量库 | Chroma / Qdrant / Milvus | **Milvus Lite + Chroma 兜底** | Milvus 原生支持 BGE-M3 hybrid、milvus-lite 嵌入式零服务；Chroma 兜底保可用。 |
| ADR-8 | 记忆架构 | 单层 / 数据库 / 仿 Hermes | **仿 Hermes 3 层** | 短期/情景/长期分层清晰；append-only 树支持轨迹回放（轨迹级评估基础）。 |
| ADR-9 | 环境 | venv / conda / Docker | **conda env** | 本机 miniconda，conda 管理科学计算栈（torch/FlagEmbedding）更顺手；venv 在 torch wheel 上踩过坑。 |
| ADR-10 | HITL 策略 | 全自动 / 默认确认 / 分级 | **默认确认（高 stakes）** | 求职决策高 stakes，默认 HITL，仅低风险自动化。高级方向 Delegate 三级授权。 |
| ADR-11 | Chunking | 定长 / 语义 / Contextual | **Recursive + Contextual Chunking** | Anthropic 法减 49% 检索失败，叠加 rerank 降 67%。 |
| ADR-12 | 模型下载源 | HuggingFace / ModelScope | **ModelScope** | 本机 HF 直连被拦（SSL 断流），ModelScope 可通。 |
| ADR-13 | 文档加载 | per-format（PyMuPDF/python-docx）/ MarkItDown 统一 | **MarkItDown 统一 + Markdown 直读** | 一个库覆盖 PDF/Word/Excel/HTML 转 Markdown，与 Markdown 感知 Splitter 天然衔接；BaseLoader 抽象可回退 per-format。 |

### 3.15 Prompt 与生成参数约定【MVP 核心】

> 对齐 Agent 搭建基础 6 件套中的 Prompt / Temperature / Few-shot，确保每个 agent 输出稳定可控。

#### 3.15.1 System Prompt 结构
每个 agent 的 system prompt（`careercrew_ai/prompts/*.txt`）统一四段：
1. **身份**：你是 CareerCrew 的 XX agent，职责是…
2. **执行规则**：工具调用顺序、何时 HITL、禁止行为（如"不得未经确认投递"）
3. **输出格式**：结构化产出（JSON / 固定字段），便于下游 agent 消费
4. **禁止行为**：不幻觉、不越权、不输出敏感字段

#### 3.15.2 Temperature 按场景
| Agent | 温度 | 理由 |
|-------|------|------|
| 职位匹配官 / 简历顾问 / 谈判师 | 0.1-0.3 | 严谨，匹配/定制/谈薪要准，减少虚构 |
| 面试官 / 职业规划师 | 0.5-0.7 | 需要发散（出题多样性、规划建议） |

> 默认 `temperature: 0.3`（§5.5），各 agent 按需在 `init_chat_model` 调用时覆盖。

#### 3.15.3 Few-shot 少样本示例
- **适用**：输出格式经常不规范时，在 prompt 里补 3-5 条标准示例对齐格式。
- **优先于微调**：轻量化方案，低成本对齐输出规范（对齐框架 #8，微调是最后手段）。
- **位置**：`careercrew_ai/prompts/*_fewshot.txt`（按需，非每个 agent 都要）。

---

## 4. 测试方案

### 4.1 设计理念：测试驱动开发 (TDD)

本项目采用 **TDD** 作为核心开发范式，每个组件实现前先明确预期行为。

**核心原则**：
- **早测试、常测试**：每个模块实现同时编写单元测试。
- **测试即文档**：测试用例是行为规范，新开发者读测试即可理解模块功能。
- **快速反馈循环**：单元测试秒级完成，支持高频执行。
- **分层测试金字塔**：大量单元测试为基座，中量集成测试保障协作，少量 E2E 验证完整流程。

```
        /\
       /E2E\         <- 少量：求职闭环关键流程
      /------\
     /Integration\   <- 中量：supervisor+agent+工具+记忆协作
    /------------\
   /  Unit Tests  \  <- 大量：单个函数/类（ReAct 循环、记忆读写、工具路由）
  /________________\
```

### 4.2 测试分层策略

#### 4.2.1 单元测试 (Unit Tests)
隔离外部依赖（LLM / Milvus / MCP），验证内部逻辑。

| 模块 | 测试重点 | 典型用例 |
|------|---------|---------|
| **ReAct 内核** | 循环逻辑、轮次上限、工具调用判定 | Mock LLM 返回 tool_call -> 验证执行+回喂；无 tool_call -> 验证 break；超轮次 -> 抛错 |
| **记忆 - 情景** | append-only、parentId 树、回溯重建 | 写入后 parentId 链正确；从叶子回溯到根拼接上下文完整 |
| **记忆 - User Model** | 结构化读写、字段约束 | `profile_update` 更新字段；非法字段拒绝 |
| **记忆 - compaction** | 触发阈值、保留区、压缩条目 | token 占比超阈值触发；保留区原封；compaction 条目带 `firstKeptEntryId` |
| **工具注册表** | 注册、路由、requires_confirmation | MCP/内部工具统一 schema；高风险工具触发节点内 `interrupt()` 挂起 |
| **supervisor 路由** | 阶段->agent 路由 | 意图+阶段 -> 正确 agent；多 agent 会诊 fan-out |
| **Milvus 后端** | upsert/query 契约 | roundtrip 确定性；Dense+Sparse 混合检索；collection 隔离 |

**技术选型**：`pytest` + `unittest.mock`/`pytest-mock` + `pytest-check`。

#### 4.2.2 集成测试 (Integration Tests)
验证多组件协作。

| 场景 | 验证要点 |
|------|---------|
| **supervisor + agent + ReAct** | 路由到 agent -> ReAct 执行工具 -> 返回 supervisor |
| **agent + 记忆** | ReAct 主动 `memory_search` -> 结果回喂 -> 写情景记忆 |
| **agent + RAG** | `rag_query` 调自建 RAG 检索 -> 结果回喂 |
| **HITL 流程** | 高风险工具 -> interrupt -> 人工确认 -> 恢复 -> 写记忆 |
| **Milvus + RAG** | 知识库 ingestion -> 检索 roundtrip（真实 milvus-lite） |

#### 4.2.3 端到端测试 (E2E Tests)
模拟真实求职闭环：
- **场景 1：意向->匹配->简历** 部分闭环（M1 验收）。
- **场景 2：面试模拟** 出题->问答->评分->写面经。
- **场景 3：HITL 投递** 谈薪->确认投递->跟踪->复盘。
- **场景 4：dogfood** 用自身知识库跑完整求职周期。

### 4.3 Agent 行为评估测试

针对 agent 系统特有的评估（区别于普通函数测试）：

1. **路由准确率**：给定意图+阶段，supervisor 是否路由到正确 agent（golden 路由集）。
2. **工具调用合理性**：precision/recall（该调的调了没、不该调的乱调没）。
3. **记忆利用率**：`memory_hit_rate`（已有相关记忆时是否被检索利用）。
4. **HITL 触发正确性**：高风险动作是否必然触发确认、低风险是否不误触发。
5. **ReAct 效率**：达到目标所需轮次（避免无谓多轮）。
6. **Grounding**：答案是否有知识库/记忆依据（不幻觉）。

> 轨迹级量化评估（LLM-as-judge + 黄金回放）属高级方向，MVP 阶段用 golden 集断言 + 人工抽检。

### 4.4 测试工具链

- **框架**：`pytest`（参数化、Fixture）。
- **Mock**：`unittest.mock`（LLM / MCP / Milvus）。
- **Agent 评估**：golden 路由集 + golden 轨迹集（`tests/fixtures/`）。
- **CI**：GitHub Actions（`.github/workflows/ci.yml`），push / PR 触发；CI 跑轻量单测（配置加载 + AI 工厂契约，外部依赖全 mock，**无需 API key**）；重 ML 栈（FlagEmbedding / torch / BGE-M3）由本地 conda env 验证（D 阶段起涉及）。
- **覆盖率目标**：单元测试核心逻辑 ≥ 80%；E2E 至少 4 个关键流程；**关键集成路径**（§4.2.2 的 5 条：supervisor+agent+ReAct / agent+记忆 / agent+RAG / HITL 流程 / Milvus+RAG）**各至少 1 个用例**（不追求集成层覆盖率数字，以路径清单为准）。

---

## 5. 系统架构与模块设计

### 5.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          前端层 (CLI / Dashboard)                            │
│                                                                             │
│    ┌──────────────────────┐              ┌──────────────────────┐           │
│    │   CLI (careercrew_ui)│              │ Streamlit Dashboard  │           │
│    │  交互渲染 + HITL 提示 │              │ 系统总览/数据/追踪    │           │
│    └──────────┬───────────┘              └──────────┬───────────┘           │
│               │          订阅事件 / 调用产品层            │                    │
└───────────────┼───────────────────────────────────────┼─────────────────────┘
                │                                       │
                ▼                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  产品层 (careercrew_cli) - 工作流 + HITL                      │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    求职周期工作流编排 (Workflow)                        │  │
│  │   intent->planning->match->resume->interview->negotiate->apply->track │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────┐                                                    │
│  │   HITL 闸门管理       │  interrupt / 确认 / 拒绝 / 修改                    │
│  └──────────┬───────────┘                                                    │
└─────────────┼───────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              核心层 (careercrew_core) - 编排 + Agent + 记忆 + 工具            │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                  LangGraph Supervisor (路由/HITL/checkpointer)         │  │
│  │            stage + user_intent -> route to agent / interrupt / end     │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │ 路由                                  │
│    ┌───────────┬───────────┬─────────┴────────┬───────────┬───────────┐    │
│    ▼           ▼           ▼                  ▼           ▼           ▼    │
│ ┌────────┐ ┌────────┐ ┌────────┐  ┌────────────────┐ ┌────────┐ ┌────────┐│
│ │job_    │ │resume_ │ │inter-  │  │salary_         │ │career_ │ │ 多agent ││
│ │matcher │ │advisor │ │viewer  │  │negotiator      │ │planner │ │ 会诊   ││
│ └───┬────┘ └───┬────┘ └───┬────┘  └───────┬────────┘ └───┬────┘ └────────┘│
│     │          │          │               │              │        (高级)   │
│     └──────────┴──────────┴───────┬───────┴──────────────┘                 │
│                                    ▼                                        │
│             ┌──────────────────────────────────────────┐                    │
│             │       手写 ReAct 循环内核 (可见 while)    │                    │
│             │  组装上下文->调LLM->判tool_call->执行->回喂 │                    │
│             └──────────────────────┬───────────────────┘                    │
│                                    │ 调用                                   │
│     ┌──────────────────────────────┼──────────────────────────────┐         │
│     ▼                              ▼                              ▼         │
│ ┌────────────────┐    ┌─────────────────────┐       ┌────────────────────┐  │
│ │  工具注册表     │    │     记忆系统 (3层)   │       │   Trace 打点       │  │
│ │ ┌────────────┐ │    │ 短期: Context Window│       │ (自建 TraceContext) │  │
│ │ │rag_query   │ │    │ 情景: JSONL+树+向量 │       │  agent_loop/hitl/  │  │
│ │ │memory_search││    │ 长期: User Model    │       │  memory_op/compact │  │
│ │ │profile_upd │ │    │ compaction (基础版) │       └────────────────────┘  │
│ │ │mcp-jobs    │ │    └─────────────────────┘                               │
│ │ │google_mcp  │ │                                                         │
│ │ └────────────┘ │                                                         │
│ │ requires_conf..│                                                         │
│ └────────────────┘                                                         │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
┌──────────────────────┐ ┌─────────────────────┐ ┌──────────────────────────┐
│ AI 层 (careercrew_ai)│ │  RAG 流水线 (自建)   │ │       存储层              │
│ init_chat_model     │ │ BGE-M3 + Rerank     │ │  Milvus Lite (KB+记忆)   │
│ Embedding/Reranker  │ │ Hybrid + RRF        │ │  SQLite checkpointer     │
│ agent prompts        │ │ + bge-reranker-v2   │ │  JSONL transcripts       │
│                      │ │ + Milvus/Chroma     │ │  user_model.json         │
└──────────────────────┘ └─────────────────────┘ │  traces.jsonl            │
                                                  └──────────────────────────┘
```

### 5.2 目录结构

```
CareerCrew/
│
├── careercrew_ai/                       # AI 基础层（LLM 适配 / embedding / rerank / vector_store）
│   ├── __init__.py
│   ├── llm/                             # LLM 适配（init_chat_model，不自建 BaseLLM）
│   │   ├── __init__.py
│   │   └── llm_adapter.py              # create_llm(settings) -> init_chat_model(硅基流动)
│   ├── embedding/                       # BGE-M3 三合一（dense + sparse + colbert）
│   │   ├── __init__.py
│   │   └── bge_m3_embedding.py         # BaseEmbedding + BGE-M3 实现
│   ├── reranker/                        # Rerank（硅基流动 API）
│   │   ├── __init__.py
│   │   ├── base_reranker.py            # BaseReranker 抽象
│   │   └── siliconflow_reranker.py     # 硅基流动 rerank API（bge-reranker-v2-m3）
│   ├── vector_store/                    # 向量库可插拔
│   │   ├── __init__.py
│   │   ├── base_vector_store.py        # BaseVectorStore 抽象
│   │   ├── milvus_store.py             # Milvus 后端（BGE-M3 hybrid）
│   │   └── chroma_store.py             # Chroma 兜底
│   ├── splitter/                        # 切分策略
│   │   ├── __init__.py
│   │   └── recursive_splitter.py       # RecursiveCharacterTextSplitter（Markdown 感知）
│   ├── react/                           # 手写 ReAct 循环内核
│   │   ├── __init__.py
│   │   ├── react_loop.py               # 可见 while 循环（组装上下文->调LLM->判tool_call->执行->回喂）
│   │   └── context_builder.py          # 上下文组装（短期对话+记忆+工具结果）
│   └── prompts/                         # agent system prompts + RAG prompts（运行时 prompts 唯一存放位置；根 prompts/ 仅为开发模板）
│       ├── job_matcher.txt
│       ├── resume_advisor.txt
│       ├── interviewer.txt
│       ├── salary_negotiator.txt
│       ├── career_planner.txt
│       └── contextual_chunking.txt     # Contextual Chunking 上下文生成 prompt
│
├── careercrew_core/                     # 核心层（LangGraph + Agent + 记忆 + 工具）
│   ├── __init__.py
│   ├── state/                           # Thread State + checkpointer
│   │   ├── __init__.py
│   │   ├── thread_state.py             # CareerCrewState TypedDict
│   │   └── checkpointer.py             # SQLite checkpointer 封装
│   ├── supervisor/                      # LangGraph supervisor 编排
│   │   ├── __init__.py
│   │   ├── graph.py                    # 图构建（节点+边+路由）
│   │   ├── router.py                   # 阶段->agent 路由逻辑
│   │   └── hitl.py                     # interrupt / 确认恢复
│   ├── agents/                          # 5 个 agent 节点
│   │   ├── __init__.py
│   │   ├── base_agent.py               # agent 节点基类（套 ReAct 循环）
│   │   ├── job_matcher.py
│   │   ├── resume_advisor.py
│   │   ├── interviewer.py
│   │   ├── salary_negotiator.py
│   │   └── career_planner.py
│   ├── memory/                          # 3 层记忆系统
│   │   ├── __init__.py
│   │   ├── types.py                    # MemoryEntry / TreeNode / UserModel
│   │   ├── short_term.py               # 短期 Context Window 管理
│   │   ├── episodic.py                 # append-only JSONL + parentId 树 + 回溯重建
│   │   ├── user_model.py               # 长期 User Model 结构化读写
│   │   ├── vector_index.py             # 情景记忆向量索引（Milvus）
│   │   └── compaction.py               # compaction 基础版（保留区+压缩区）
│   ├── rag/                             # 自建 RAG 流水线
│   │   ├── __init__.py
│   │   ├── loaders/                    # 文档加载（多格式）
│   │   │   ├── __init__.py
│   │   │   ├── base_loader.py           # BaseLoader 抽象
│   │   │   ├── markdown_loader.py       # Markdown 直读
│   │   │   └── markitdown_loader.py     # MarkItDown 统一转 PDF/Word/Excel/HTML
│   │   ├── chunking/                   # 切分 + Contextual Chunking
│   │   │   ├── __init__.py
│   │   │   ├── document_chunker.py     # Document -> Chunks（调用 ai.splitter）
│   │   │   └── contextualizer.py       # LLM 给每块生成上下文前置（Anthropic 法）
│   │   ├── retrieval/                  # Hybrid 检索
│   │   │   ├── __init__.py
│   │   │   ├── hybrid_search.py        # BGE-M3 dense + sparse 并行召回
│   │   │   └── fusion.py               # RRF 融合
│   │   ├── rerank.py                   # 编排 ai.reranker（None/Cross-Encoder 回退）
│   │   └── pipeline.py                 # Ingestion 编排：load->split->contextualize->embed->upsert
│   └── tools/                           # 统一工具注册表
│       ├── __init__.py
│       ├── registry.py                 # 工具注册表（统一 schema + requires_confirmation）
│       ├── internal/                   # 内部函数工具
│       │   ├── rag_query.py            # 封装自建 RAG 检索
│       │   ├── memory_search.py        # 主动记忆检索
│       │   ├── memory_write.py         # 写情景记忆
│       │   └── profile_update.py       # 更新 User Model
│       └── mcp/                         # MCP 工具接入
│           ├── mcp_client.py           # MCP client（发现+注册 mcp-jobs/Google MCP）
│           └── mock_apply.py           # MVP 投递/进度跟踪 mock
│
├── careercrew_cli/                      # 产品层（工作流 + HITL + 入口）
│   ├── __init__.py
│   ├── workflow/                        # 求职周期工作流闭环
│   │   ├── __init__.py
│   │   └── job_cycle.py                # intent->...->review->循环 编排
│   ├── hitl/                            # 人工闸门
│   │   ├── __init__.py
│   │   └── gates.py                    # 投递/打招呼/接offer/谈薪话术 闸门
│   └── app.py                           # CLI 入口（命令分发）
│
├── careercrew_ui/                       # UI 层（CLI 渲染 + Streamlit）
│   ├── __init__.py
│   ├── cli/                             # CLI 渲染
│   │   ├── __init__.py
│   │   └── renderer.py                 # 对话渲染 + HITL 提示
│   └── dashboard/                       # Streamlit Dashboard
│       ├── __init__.py
│       ├── app.py                      # Streamlit 入口
│       └── pages/
│           ├── overview.py             # 系统总览
│           ├── data_browser.py         # User Model / 情景记忆树 / 候选数据
│           └── traces.py               # agent ReAct 轨迹 / HITL 历史
│
├── config/                              # 配置文件
│   └── settings.yaml                    # 主配置（agent prompts 唯一位置：careercrew_ai/prompts/）
│
├── data/                                # 数据目录
│   ├── db/
│   │   ├── milvus/                      # Milvus Lite 嵌入式（KB + 情景记忆向量）
│   │   ├── checkpointer.db              # LangGraph SQLite checkpointer
│   │   └── (chroma 兜底目录)
│   ├── transcripts/                     # 情景记忆 JSONL（{user_id}/{thread_id}.jsonl）
│   │   └── {user_id}/
│   ├── user_model.json                  # 长期 User Model
│   └── knowledge/                       # 知识库原始文档（八股/面经/JD/简历范本）
│
├── logs/                                # 日志
│   ├── traces.jsonl                     # 全链路 trace（自建格式）
│   └── app.log
│
├── tests/                               # 测试
│   ├── unit/
│   │   ├── test_react_loop.py
│   │   ├── test_episodic_memory.py
│   │   ├── test_user_model.py
│   │   ├── test_compaction.py
│   │   ├── test_tool_registry.py
│   │   ├── test_supervisor_router.py
│   │   ├── test_bge_m3_embedding.py
│   │   ├── test_hybrid_search_rrf.py
│   │   ├── test_contextual_chunking.py
│   │   ├── test_milvus_store.py
│   │   └── ...
│   ├── integration/
│   │   ├── test_supervisor_agent_react.py
│   │   ├── test_agent_memory.py
│   │   ├── test_agent_rag.py
│   │   ├── test_hitl_flow.py
│   │   └── test_milvus_backend.py
│   ├── e2e/
│   │   ├── test_match_resume_loop.py    # M1 闭环
│   │   ├── test_interview_sim.py
│   │   ├── test_apply_hitl.py
│   │   └── test_dogfood_cycle.py
│   └── fixtures/
│       ├── golden_routes.json           # 路由 golden 集
│       └── golden_trajectories/         # 轨迹 golden 集
│
├── scripts/
│   ├── ingest_knowledge.py              # 知识库摄取（自建 pipeline）
│   ├── run_cli.py                       # CLI 启动
│   └── start_dashboard.py               # Dashboard 启动
│
├── pyproject.toml                       # 依赖：langgraph / langchain / langchain-openai / pymilvus / FlagEmbedding / modelscope / markitdown / ragas / pytest
└── README.md
```

> **依赖说明**：`pyproject.toml` 依赖 `langgraph` / `langchain`+`langchain-openai`(init_chat_model + ChatOpenAI) / `pymilvus`(milvus-lite) / `FlagEmbedding`(BGE-M3 三合一) / `modelscope`(BGE-M3 下载，HF 直连被拦) / `markitdown`(多格式文档加载) / `ragas`(评估) / `pytest`。CareerCrew **不依赖外部 RAG 项目**，RAG 流水线全部自建于 `careercrew_ai` 与 `careercrew_core/rag`。

### 5.3 模块职责表

#### 5.3.1 AI 层 (`careercrew_ai`)

| 模块 | 职责 | 关键技术点 |
|------|------|-----------|
| `llm/llm_adapter.py` | `create_llm(settings)` 适配（`init_chat_model`） | 硅基流动 base_url + model 配置 |
| `react/react_loop.py` | 手写 ReAct 可见 while 循环 | 解析 tool_calls、轮次上限、异常中断 |
| `react/context_builder.py` | 每轮上下文组装 | 短期对话 + 按需检索记忆 + 工具结果 |
| `prompts/*.txt` | 5 个 agent 的 system prompt + contextual_chunking | 角色定义 + 工具使用指引 |
| `embedding/bge_m3_embedding.py` | BGE-M3 三合一编码 | dense + sparse + colbert 一次前向 |
| `reranker/siliconflow_reranker.py` | 硅基流动 rerank API | bge-reranker-v2-m3，None 回退 |
| `vector_store/milvus_store.py` | Milvus 向量库后端 | BGE-M3 hybrid，collection 隔离 |
| `splitter/recursive_splitter.py` | Markdown 感知切分 | RecursiveCharacterTextSplitter |

#### 5.3.2 核心层 (`careercrew_core`)

| 模块 | 职责 | 关键技术点 |
|------|------|-----------|
| `state/thread_state.py` | Thread 状态定义 | `CareerCrewState` TypedDict |
| `state/checkpointer.py` | 短期状态持久化 | SQLite checkpointer（WAL） |
| `supervisor/graph.py` | LangGraph 图构建 | 节点+边+条件路由 |
| `supervisor/router.py` | 阶段->agent 路由 | 状态机路由逻辑 |
| `supervisor/hitl.py` | HITL interrupt 与恢复 | `interrupt` + 确认回填 |
| `agents/base_agent.py` | agent 节点基类 | 套 ReAct 循环 + 产出格式化 |
| `agents/*` | 5 个专职 agent | 各自 prompt + 工具子集 |
| `memory/episodic.py` | 情景记忆 append-only 树 | JSONL + parentId + 回溯重建 |
| `memory/user_model.py` | User Model 读写 | 结构化字段约束 |
| `memory/vector_index.py` | 情景记忆向量索引 | Milvus collection 隔离 |
| `memory/compaction.py` | compaction 基础版 | token 占比触发 + 保留区 + 压缩区 |
| `rag/loaders/markitdown_loader.py` | PDF/Word/Excel 转 Markdown | MarkItDown 统一加载多格式 |
| `rag/loaders/markdown_loader.py` | Markdown 直读 | 保留标题层级 |
| `rag/chunking/contextualizer.py` | Contextual Chunking | LLM 给每块生成上下文前置 |
| `rag/retrieval/hybrid_search.py` | Hybrid 检索编排 | BGE-M3 dense+sparse 召回 + RRF 融合 |
| `rag/pipeline.py` | Ingestion 编排 | load->split->contextualize->embed->upsert |
| `tools/registry.py` | 统一工具注册表 | 统一 schema + `requires_confirmation` |
| `tools/internal/*` | 内部函数工具 | rag_query / memory_search / memory_write / profile_update |
| `tools/mcp/mcp_client.py` | MCP 工具发现与注册 | mcp-jobs / Google MCP |

#### 5.3.3 产品层 (`careercrew_cli`)

| 模块 | 职责 | 关键技术点 |
|------|------|-----------|
| `workflow/job_cycle.py` | 求职周期闭环编排 | 阶段流转 + 循环陪跑 |
| `hitl/gates.py` | 人工闸门 | 投递/打招呼/接offer/谈薪话术 |
| `app.py` | CLI 入口 | 命令分发 |

#### 5.3.4 UI 层 (`careercrew_ui`)

| 模块 | 职责 | 关键技术点 |
|------|------|-----------|
| `cli/renderer.py` | CLI 对话渲染 | HITL 提示、agent 输出格式化 |
| `dashboard/app.py` | Streamlit 入口 | 多页面导航 |
| `dashboard/pages/overview.py` | 系统总览 | agent 配置 + 记忆统计 + 当前阶段 |
| `dashboard/pages/data_browser.py` | 数据浏览 | User Model / 情景记忆树 / 候选数据 |
| `dashboard/pages/traces.py` | 追踪查看 | ReAct 轨迹回放 / HITL 历史 |

### 5.4 数据流说明

#### 5.4.1 Agent 编排流（单轮 supervisor -> agent -> 工具）

```
用户输入 + 当前阶段
      │
      ▼
┌─────────────────┐
│   Supervisor    │  读 state -> 判断阶段 -> 路由到 agent
│   (router)      │
└────────┬────────┘
         │ route(agent_name)
         ▼
┌─────────────────┐
│  Agent 节点     │  套手写 ReAct 循环
│  (base_agent)   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│        ReAct while 循环              │
│  组装上下文(短期+记忆+工具结果)       │
│       ▼                             │
│  调 LLM(带工具 schema)              │
│       ▼                             │
│  有 tool_call? ──是──> 执行工具 ──┐ │
│       │ 否                        ▼ │
│       ▼                       回喂结果│
│  返回最终答案 <────────────────────┘ │
└────────────────┬────────────────────┘
                 │ 工具执行前检查
                 ▼
        requires_confirmation?
           │              │
          是              否
           ▼              ▼
    ┌────────────┐   直接执行
    │ HITL       │
    │ interrupt  │
    └─────┬──────┘
          │ 确认/拒绝/修改
          ▼
    执行(或中止) -> 写情景记忆
```

#### 5.4.2 记忆读写流

```
【写入】关键事件触发
面试结束 / 投递 / offer / 匹配命中
      │
      ▼
episodic.write(entry)  ──> append JSONL (id+parentId)
      │
      └──> vector_index.upsert(embedding) ──> Milvus (careercrew_episodic)

profile_update(字段) ──> user_model.json 结构化更新

【读取】上下文重建 + 主动检索
ReAct 组装上下文:
  ├─ short_term: state.messages (Context Window)
  ├─ episodic 回溯: 从当前叶子沿 parentId 到根拼接
  └─ memory_search(主动): query -> Milvus 语义检索情景记忆 -> top_k 注入
```

#### 5.4.3 求职周期工作流

```
intent -> planning(规划师:画像+目标公司池)
              -> match(匹配官:搜JD+打分+入库)
                   -> resume(简历顾问:定制+评估)
                        -> interview(面试官:模拟+记录)
                             -> negotiate(谈判师:策略+话术)
                                  -> apply(HITL确认投递) [interrupt]
                                       -> track(跟踪, mock/自建MCP)
                                            -> review(复盘写记忆)
                                                 -> 回 match (循环)
```

#### 5.4.4 RAG 检索流（自建）

```
agent 调 rag_query 工具
      │
      ▼
自建 HybridSearch
  ├─ Dense (Embedding) ──┐
  ├─ Sparse (BGE-M3)    ──┤──> RRF 融合 ──> Rerank ──> Top-K
  └─ 向量库: Milvus (careercrew_kb) ──┘
      │
      ▼
结果回喂 ReAct 循环
```

### 5.5 配置驱动设计

系统通过 `config/settings.yaml` 统一配置，支持零代码切换组件：

```yaml
# config/settings.yaml 示例

# LLM 配置（硅基流动，OpenAI 兼容；init_chat_model 适配）
llm:
  provider: openai           # 走 init_chat_model 的 openai provider（OpenAI 兼容）
  model: "deepseek-ai/DeepSeek-V4-Flash"   # 默认 Flash（便宜快，工具调用已验证）；可换 V4-Pro/V3.2/GLM 等
  base_url: "https://api.siliconflow.cn/v1"
  api_key: "${SILICONFLOW_API_KEY}"
  temperature: 0.3           # 默认；按 agent 场景调（见 §3.15.2）
  max_tokens: 2048           # 单次响应上限
  max_tokens_per_run: 60000  # 单次运行 token 成本预算（超则停 + 告警，见 §5.7）

# Embedding 配置（本地 BGE-M3 三合一：dense + sparse + colbert）
embedding:
  provider: bge_m3_local      # 本地 FlagEmbedding；bge_m3_local | openai | siliconflow_dense
  model: BAAI/bge-m3
  # 本地跑才能拿 dense+sparse+colbert；API 只给 dense。稀疏路免额外 BM25 索引

# Rerank 配置（硅基流动 rerank API）
rerank:
  backend: siliconflow        # none | siliconflow | local_bge
  model: BAAI/bge-reranker-v2-m3
  base_url: "https://api.siliconflow.cn/v1"
  api_key: "${SILICONFLOW_API_KEY}"
  top_m: 30                   # 精排候选数

# 向量库配置（Milvus 可插拔）
vector_store:
  backend: milvus_lite       # milvus_lite | milvus_docker | chroma
  persist_path: ./data/db/milvus
  collections:
    knowledge: careercrew_kb
    episodic_memory: careercrew_episodic

# RAG 检索配置（自建）
rag:
  retrieval:
    mode: hybrid             # hybrid | dense | sparse
    fusion_algorithm: rrf    # rrf | weighted_sum
    top_k_dense: 20
    top_k_sparse: 20
    top_k_final: 10
  chunking:
    strategy: recursive      # recursive | semantic
    chunk_size: 800
    chunk_overlap: 100
    contextual: true         # Contextual Chunking（LLM 加上下文前置）
  loaders:
    backend: markitdown        # markitdown | pymupdf | python-docx（per-format 回退）

# LangGraph supervisor 配置
supervisor:
  checkpointer:
    backend: sqlite
    path: ./data/db/checkpointer.db
  max_consecutive_agent_turns: 10

# 记忆系统
memory:
  episodic:
    transcript_dir: ./data/transcripts
    vectorize: true
  user_model:
    path: ./data/user_model.json
  compaction:
    enabled: true
    token_threshold_ratio: 0.7   # token 占比阈值（用模型真实 usage）
    retention_tokens: 20000       # 保留区大小

# 工具层
tools:
  registry:
    internal: [rag_query, memory_search, memory_write, profile_update]
    mcp: [mcp_jobs, google_mcp]
  hitl:
    requires_confirmation:
      - submit_application
      - send_greeting
      - accept_offer
      - salary_talk_script

# HITL 默认策略
hitl:
  default_policy: confirm        # 默认 HITL，仅低风险自动化

# 可观测性（自建 trace）
observability:
  enabled: true
  log_file: ./logs/traces.jsonl

# Dashboard
dashboard:
  enabled: true
  port: 8501
  traces_dir: ./logs
```

### 5.6 扩展性设计要点

1. **新增 agent**：继承 `base_agent`，加 system prompt，在 `supervisor/router.py` 注册路由。
2. **新增工具**：实现统一 schema，在 `tools/registry.py` 注册；MCP 工具自动发现。
3. **换向量库**：改 `vector_store.backend` 配置（milvus_lite / milvus_docker / chroma）。
4. **换 LLM**：改 `llm` 配置（init_chat_model 适配）。
5. **加高级记忆能力**：在 `memory/` 下扩展 Skill Library / 反思循环等（高级方向）。
6. **多用户边界**：MVP 为**单用户**——transcripts 按 `{user_id}/` 组织仅为结构预留，MVP 统一用默认 user_id；checkpointer / User Model / 向量 collection 不做多租户隔离。多用户（Postgres checkpointer + 用户数据分库）见 §7 长期愿景。

### 5.7 错误处理与降级策略

> 每个外部依赖与关键组件的失败场景 + 降级，确保单点失败不阻塞主流程。

| 组件 | 失败场景 | 降级策略 |
|------|---------|---------|
| LLM（硅基流动） | 超时 / 限流 / 5xx | 指数退避重试 ≤3 次；仍失败抛可读错误（含 trace_id），不吞异常 |
| LLM | API key 错 / 余额不足 / 模型名不存在 | A3 配置校验只做 key 非空等静态检查（`create_llm` 构造不触网）；模型名 / 余额 / 连通性探活由 `careercrew config --check` 落地（G 阶段 CLI 完善时补）；首次 invoke 前的运行时错误按"重试 → 可读错误（含 trace_id）"处理 |
| LLM | 单次运行 token 超 `max_tokens_per_run` 预算 | 停止当前 run + 告警 + trace 记录，防止成本失控 |
| BGE-M3 编码 | 模型加载失败 / 编码异常 | 跳过该块 + 记录警告，不阻塞整批 ingestion |
| Milvus | 连接失败 / 查询超时 | 切 Chroma 兜底（`backend=chroma`）；无兜底则返回空结果 + 错误日志 |
| Rerank（硅基流动） | 超时 / 失败 | 回退 NoneReranker（原 RRF 排序），不阻塞检索 |
| MCP 工具（mcp-jobs/Google） | 超时 / 不可用 | 工具返回错误信息给 agent，agent 决定重试/换路径；MVP 用 mock 兜底 |
| Contextual Chunking LLM | 生成上下文失败 | 该块不加上下文前缀（降级为普通块），继续 ingestion |
| compaction | 总结 LLM 失败 | 保留原 state 不压缩，记录警告，下轮重试 |
| 情景记忆写入 | JSONL 写失败 | 重试；失败则内存暂存 + 告警（不丢数据） |
| checkpointer | SQLite 锁 / 写失败 | 重试；失败则降级内存 checkpointer（进程内，重启丢失） |

**原则**：检索/生成链路任何环节失败都走"降级 + 可观测"，不让用户看到原始 stack trace；高风险动作（投递/接 offer）即使降级也必走 HITL 确认。

### 5.8 安全与隐私

- **API key**：通过环境变量注入（`${SILICONFLOW_API_KEY}`），不硬编码；`.gitignore` 排除 `.env`。`package` skill 打包时自动 sanitize。
- **用户数据**：简历 / 薪资 / 面经属敏感信息，存本地（`data/`），不上传第三方；User Model 结构化存储，不外泄。
- **投递动作**：必走 HITL 确认，避免误投（求职高 stakes）。
- **日志脱敏**：trace 日志不记录完整简历正文 / 薪资数字，只记摘要 + 长度 + 来源。
- **依赖安全**：MVP 阶段 `pyproject.toml` 用兼容范围（`>=`），关键 AI 依赖以 §3.1.6 实测版本为准；后续引入 lockfile（uv / pip-tools）固定完整版本后，再定期 `pip audit`。

---

## 6. 项目排期

> **排期原则（严格对齐本 DEV_SPEC 的架构分层与目录结构）**
>
> - **只按本文档设计落地**：以 5.2 节目录树为"交付清单"，每步在文件系统上产生可见变化。
> - **1 小时一个可验收增量**：每个小阶段（≈1h）给出"验收标准 + 测试方法"，尽量 TDD。
> - **先打通主闭环，再补高级亮点**：MVP 在 A-L，跑通求职闭环；高级亮点挑 1-2 个放 M-N。
> - **外部依赖可替换/可 Mock**：LLM / Milvus / MCP 真实调用在单元测试中一律 Fake/Mock，集成测试再开真实后端。
> - **环境**：所有命令在 conda env `careercrew` 下运行（`conda activate careercrew` 或 `conda run -n careercrew ...`）。

### 阶段总览（大阶段 -> 目的）

| 阶段 | 目的 | 层级 |
|------|------|------|
| **A** 工程骨架与配置 | 可运行/可配置/可测试的工程骨架 | MVP |
| **B** LangGraph supervisor + 手写 ReAct 骨架 | 编排与 agent 内核可跑通 | MVP |
| **C** 3 层记忆 + append-only 树 | 记忆系统基础版 | MVP |
| **D** 自建 RAG 流水线 | BGE-M3 + Contextual Chunking + Hybrid + Rerank 跑通 | MVP |
| **E** 职位匹配官 | 第一个 agent 落地 | MVP |
| **F** 简历顾问 | 第二个 agent + RAG 简历定制 | MVP |
| **G** CLI + M1 闭环 | 部分求职闭环可跑通 | MVP |
| **H** 面试官 + 情景记忆 | 面试模拟 + 记忆写入 | MVP |
| **I** 记忆按需检索 + compaction 基础版 | 记忆主动检索 + 压缩 | MVP |
| **J** 谈判师 + 规划师 | 补齐 5 agent | MVP |
| **K** HITL 接工具层 | 高风险闸门落地 | MVP |
| **L** 评估 + Dashboard | 评估闭环 + 可视化 | MVP |
| **M** 高级亮点（选 1-2） | Loop / flush / 会诊 / Agentic RAG / Self-RAG / RAPTOR / ColBERT | 高级 |
| **N** 自建 MCP + dogfood + 收尾 | 真实投递 + 拿 offer 验收 | 高级 |

---

### 📊 进度跟踪表 (Progress Tracking)

> **状态说明**：`[ ]` 未开始 | `[~]` 进行中 | `[x]` 已完成
>
> **更新时间**：每完成一个子任务后更新对应状态

#### 阶段 A：工程骨架与配置

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| A1 | 四层目录骨架 + conda env `careercrew` + pyproject.toml + `pip install -e .` | [x] | 2026-07-30 | conda env + 依赖安装进 env |
| A2 | 引入 pytest 并建立测试目录约定 | [x] | 2026-07-30 | tests/unit\|integration\|e2e\|fixtures |
| A3 | 配置加载与校验（Settings） | [x] | 2026-07-30 | settings.yaml + load_settings + fail-fast |
| A4 | AI 基础层（LLM 适配 + embedding/vector_store/reranker 抽象） | [x] | 2026-07-30 | init_chat_model + Base* 抽象+工厂 |

#### 阶段 B：LangGraph supervisor + 手写 ReAct 骨架

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| B1 | Thread State 定义 + SQLite checkpointer | [x] | 2026-07-30 | CareerCrewState + checkpointer |
| B2 | 手写 ReAct 循环内核（可见 while） | [x] | 2026-07-30 | react_loop.py + 轮次上限 |
| B3 | LangGraph supervisor 骨架（路由） | [x] | 2026-07-30 | graph.py + router.py |
| B4 | agent 节点基类（套 ReAct） | [x] | 2026-07-30 | base_agent.py |
| B5 | 基础工具注册表 + 1 个内部工具 stub | [x] | 2026-07-30 | registry.py + memory_search stub |

#### 阶段 C：3 层记忆 + append-only 树

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| C1 | 记忆核心数据类型（MemoryEntry/TreeNode/UserModel） | [x] | 2026-07-30 | memory/types.py |
| C2 | 情景记忆 append-only JSONL + parentId 树 | [x] | 2026-07-30 | episodic.py |
| C3 | 从叶子回溯到根重建上下文 | [x] | 2026-07-30 | episodic.rebuild_context |
| C4 | 短期 Context Window 管理 | [x] | 2026-07-30 | short_term.py |
| C5 | 长期 User Model 结构化读写 | [x] | 2026-07-30 | user_model.py + profile_update |
| C6 | 基础写入触发点（面试/投递/offer 后写） | [x] | 2026-07-30 | memory_write 工具 |

#### 阶段 D：自建 RAG 流水线

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| D1 | BGE-M3 Embedding + 切分/Contextual Chunking | [x] | 2026-07-30 | bge_m3_embedding.py / contextualizer.py |
| D2 | Milvus 后端（BaseVectorStore 实现） | [x] | 2026-07-30 | milvus_store.py（CareerCrew 自有）；Windows 装不上 milvus-lite 时改 chroma 兜底 |
| D3 | Hybrid Search + RRF + Rerank 编排 | [x] | 2026-07-30 | hybrid_search.py / fusion.py / rerank.py |
| D4 | rag_query 工具 + 知识库 ingestion pipeline | [x] | 2026-07-30 | rag_query.py / pipeline.py / ingest_knowledge.py |
| D5 | 配置切换 milvus/chroma 验证 | [x] | 2026-07-30 | 工厂路由 roundtrip 测试 |

#### 阶段 E：职位匹配官

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| E1 | job_matcher system prompt | [ ] | | prompts/job_matcher.txt |
| E2 | 接 mcp-jobs 工具（mock 先行） | [ ] | | mock_jobs 样例 JD + 真实接入可选 |
| E3 | JD 检索 + 匹配打分 | [ ] | | JD-画像匹配逻辑 |
| E4 | 命中写入候选池（情景记忆） | [ ] | | job_match 事件写入 |
| E5 | 单元/集成测试 | [ ] | | golden 路由集 |

#### 阶段 F：简历顾问

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| F1 | resume_advisor system prompt | [ ] | | prompts/resume_advisor.txt |
| F2 | 简历范本 RAG 检索 | [ ] | | rag_query 检索简历范本 |
| F3 | 简历定制生成（JD 定向） | [ ] | | 按 JD 定制简历 |
| F4 | 简历匹配度评估（集成 evaluator） | [ ] | | 答案级评估 |
| F5 | 测试 | [ ] | | |

#### 阶段 G：CLI + M1 闭环

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| G1 | CLI 渲染层 | [ ] | | careercrew_ui/cli/renderer.py |
| G2 | 工作流编排（意向->匹配->简历 部分闭环） | [ ] | | job_cycle.py 部分流转 |
| G3 | HITL 基础确认 | [ ] | | CLI yes/no 提示 |
| G4 | M1 端到端冒烟 | [ ] | | test_match_resume_loop.py |

#### 阶段 H：面试官 + 情景记忆

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| H1 | interviewer system prompt | [ ] | | prompts/interviewer.txt |
| H2 | 出题（基于 JD + 八股） | [ ] | | rag_query 检索面经 |
| H3 | 模拟问答 + 评分 | [ ] | | 问答循环 + 评分 |
| H4 | 面试记录写情景记忆 | [ ] | | interview_qa 事件 + 向量 |
| H5 | 测试 | [ ] | | |

#### 阶段 I：记忆按需检索 + compaction 基础版

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| I1 | memory_search 主动检索 | [ ] | | Milvus 语义检索情景记忆 |
| I2 | compaction 触发（token 占比，真实 usage） | [ ] | | token 阈值检测 |
| I3 | 保留区 + 压缩区分块总结 | [ ] | | 分块总结 + 合并 |
| I4 | compaction 条目写 JSONL（firstKeptEntryId） | [ ] | | 压缩条目落盘 |
| I5 | 测试 | [ ] | | 压缩无损性断言 |

#### 阶段 J：谈判师 + 规划师

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| J1 | salary_negotiator prompt + 策略 | [ ] | | prompts/salary_negotiator.txt |
| J2 | 公司/薪资公开数据检索 | [ ] | | rag_query + Google MCP |
| J3 | career_planner prompt + 画像 + 目标公司池 | [ ] | | prompts/career_planner.txt |
| J4 | 测试 | [ ] | | |

#### 阶段 K：HITL 接工具层

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| K1 | 工具 requires_confirmation 标记 | [ ] | | 注册表字段 |
| K2 | LangGraph interrupt 集成 | [ ] | | supervisor/hitl.py |
| K3 | 投递/打招呼/接 offer 闸门 | [ ] | | gates.py |
| K4 | 测试 | [ ] | | HITL 触发正确性 |

#### 阶段 L：评估 + Dashboard

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| L1 | 答案级评估（简历匹配度/面试题质量，集成 Ragas） | [ ] | | CompositeEvaluator |
| L2 | 业务级评估（转化率/通过率/offer） | [ ] | | 情景记忆事件统计 |
| L3 | 自建 trace 全链路打点 | [ ] | | agent_loop/hitl/memory_op |
| L4 | Streamlit Dashboard（总览/数据/追踪） | [ ] | | 三页面 |
| L5 | 测试 | [ ] | | |

#### 阶段 M：高级亮点（选 1-2）

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| M1 | Loop Engineering 七步闭环 + 三角色（选） | [ ] | | Goal->...->Govern |
| M2 | Pre-compaction Memory Flush（选） | [ ] | | 压缩前 flush 长期记忆 |
| M3 | 多 agent 会诊（选） | [ ] | | fan-out + join |
| M4 | Agentic RAG（query router + decomposition）（选） | [ ] | | rag/agent_router.py |
| M5 | 检索自纠正 Self-RAG / CRAG（选） | [ ] | | rag/retrieval_assessor.py |
| M6 | 层级/图 RAG（RAPTOR 或 LightRAG）（选） | [ ] | | rag/hierarchical/ |
| M7 | Late Chunking / ColBERT 多向量（选） | [ ] | | bge_m3 colbert 模式 |

#### 阶段 N：自建 MCP + dogfood + 收尾

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| N1 | 自建求职者端 MCP（Playwright+CDP 仿 boss-zhipin） | [ ] | | 投递/进度/面经采集 |
| N2 | 投递/进度跟踪接真实 MCP | [ ] | | 替换 mock |
| N3 | dogfood 拿 offer | [ ] | | 用自身知识库跑完整周期 |
| N4 | README / 文档收口 | [ ] | | 运行说明 + 面试题 + 简历建议 |
| N5 | 全链路 E2E 验收 | [ ] | | 4 个关键 E2E 全绿 |

---

### 📈 总体进度

| 阶段 | 总任务数 | 已完成 | 进度 |
|------|---------|--------|------|
| 阶段 A | 4 | 4 | 100% |
| 阶段 B | 5 | 5 | 100% |
| 阶段 C | 6 | 6 | 100% |
| 阶段 D | 5 | 5 | 100% |
| 阶段 E | 5 | 0 | 0% |
| 阶段 F | 5 | 0 | 0% |
| 阶段 G | 4 | 0 | 0% |
| 阶段 H | 5 | 0 | 0% |
| 阶段 I | 5 | 0 | 0% |
| 阶段 J | 4 | 0 | 0% |
| 阶段 K | 4 | 0 | 0% |
| 阶段 L | 5 | 0 | 0% |
| 阶段 M | 7 | 0 | 0% |
| 阶段 N | 5 | 0 | 0% |
| **总计** | **65** | **20** | **31%** |

---

## 阶段 A：工程骨架与配置（目标：先可导入，再可测试）

### A1：初始化四层目录树、conda 环境与最小可运行入口
- **目标**：创建 5.2 节四层目录骨架 + conda env `careercrew` + `pyproject.toml`，`pip install -e .` 装项目依赖。
- **修改文件**：
  - `careercrew_ai/__init__.py`、`careercrew_core/__init__.py`、`careercrew_cli/__init__.py`、`careercrew_ui/__init__.py`
  - 各子包 `__init__.py`（按目录树补齐）
  - `careercrew_cli/app.py`（最小 CLI 入口占位）
  - `config/settings.yaml`（最小可解析配置）
  - `pyproject.toml`（依赖：langgraph / langchain / langchain-openai / pymilvus / FlagEmbedding / modelscope / markitdown / ragas / pytest 等）、`README.md`、`.gitignore`
- **环境与依赖**：
  - `conda create -n careercrew python=3.12 -y`
  - `conda activate careercrew` 后 `pip install -e .`（装 pyproject.toml 定义的全部依赖进 conda env）
  - BGE-M3 模型已下至 `data/ms_cache/`（验证过，无需重下）
- **实现类/函数**：无（仅骨架）。
- **验收标准**：
  - conda env `careercrew` 存在，`pip install -e .` 成功
  - 目录结构与 DEV_SPEC 5.2 一致
  - 能导入四层包：`conda run -n careercrew python -c "import careercrew_ai, careercrew_core, careercrew_cli, careercrew_ui"`
  - 关键依赖可导入：`conda run -n careercrew python -c "import langgraph, pymilvus, FlagEmbedding, sentence_transformers"`
- **测试方法**：`conda run -n careercrew python -m compileall careercrew_ai careercrew_core careercrew_cli careercrew_ui`

### A2：引入 pytest 并建立测试目录约定
- **目标**：建立 `tests/unit|integration|e2e|fixtures` 目录与 pytest 运行基座。
- **修改文件**：
  - `pyproject.toml`（pytest 配置：testpaths、markers）
  - `tests/unit/test_smoke_imports.py`
  - `tests/fixtures/`（golden_routes.json 占位）
- **实现类/函数**：无。
- **验收标准**：`pytest -q` 可运行并通过；至少 1 个冒烟测试校验四层包 import。
- **测试方法**：`pytest -q tests/unit/test_smoke_imports.py`。

### A3：配置加载与校验（Settings）
- **目标**：实现读取 `config/settings.yaml` 的配置加载器，启动时校验关键字段。
- **修改文件**：
  - `careercrew_core/state/settings.py`（新增：Settings 数据结构 + load/validate）
  - `careercrew_cli/app.py`（启动调 `load_settings()`，缺字段 fail-fast）
  - `config/settings.yaml`（补齐字段：llm/embedding/rerank/vector_store/rag/supervisor/memory/tools/hitl/observability/dashboard）
  - `tests/unit/test_config_loading.py`
- **实现类/函数**：
  - `Settings`（dataclass：结构与最小校验，不做网络/IO）
  - `load_settings(path) -> Settings`
  - `validate_settings(settings) -> None`（必填字段检查，错误信息含字段路径如 `vector_store.backend`）
- **验收标准**：启动加载成功；缺失关键字段（如 `vector_store.backend`）时抛可读错误。
- **测试方法**：`pytest -q tests/unit/test_config_loading.py`。

### A4：AI 基础层（LLM 适配 + embedding/vector_store/reranker 抽象）
- **目标**：LLM 用 `init_chat_model` 薄适配（不自建 BaseLLM）；自建 `BaseEmbedding`/`BaseVectorStore`/`BaseReranker` 抽象 + 工厂，为 RAG 与 agent 提供可插拔底座（**不依赖外部 RAG 项目**）。
- **修改文件**：
  - `careercrew_ai/llm/llm_adapter.py`（`create_llm(settings) -> BaseChatModel`，调 `init_chat_model`，base_url 指向硅基流动）
  - `careercrew_ai/embedding/base_embedding.py`（BaseEmbedding 抽象）
  - `careercrew_ai/vector_store/base_vector_store.py`（BaseVectorStore 抽象）
  - `careercrew_ai/reranker/base_reranker.py`（BaseReranker 抽象）
  - `tests/unit/test_ai_base_factories.py`
- **实现类/函数**：
  - `create_llm(settings) -> BaseChatModel`（`init_chat_model(model, model_provider="openai", base_url=..., api_key=...)`）
  - `BaseEmbedding` / `BaseReranker` / `BaseVectorStore`（契约 + 工厂骨架，Fake 实现验证路由）
- **验收标准**：`create_llm` 按配置创建 ChatModel（Mock 验证 base_url 注入）；三个抽象工厂路由到 Fake 实现；契约测试约束 shape。
- **测试方法**：`pytest -q tests/unit/test_ai_base_factories.py`。

---

## 阶段 B：LangGraph supervisor + 手写 ReAct 骨架（目标：编排与 agent 内核可跑通）

### B1：Thread State 定义 + SQLite checkpointer
- **目标**：定义 `CareerCrewState` 并接入 LangGraph SQLite checkpointer。
- **修改文件**：
  - `careercrew_core/state/thread_state.py`
  - `careercrew_core/state/checkpointer.py`
  - `tests/unit/test_thread_state.py`
- **实现类/函数**：
  - `CareerCrewState`（TypedDict：thread_id/user_id/stage/messages/pending_action/agent_outputs/target_companies...）
  - `get_checkpointer(settings) -> BaseCheckpointSaver`（SQLite，WAL）
- **验收标准**：state 可序列化；checkpointer 可保存/恢复 thread。
- **测试方法**：`pytest -q tests/unit/test_thread_state.py`。

### B2：手写 ReAct 循环内核
- **目标**：实现可见 `while` 循环的 ReAct 内核，不依赖 agent 黑盒。
- **修改文件**：
  - `careercrew_ai/react/react_loop.py`
  - `careercrew_ai/react/context_builder.py`
  - `tests/unit/test_react_loop.py`
- **实现类/函数**：
  - `ReactLoop.run(agent_prompt, messages, tools, llm) -> AgentResult`
  - `ContextBuilder.build(messages, memory, tool_results) -> list[Message]`
- **验收标准**：Mock LLM 返回 tool_call -> 验证执行+回喂+再循环；无 tool_call -> break；超 `max_iterations` 抛错。
- **测试方法**：`pytest -q tests/unit/test_react_loop.py`。

### B3：LangGraph supervisor 骨架（路由）
- **目标**：搭建 supervisor 图，按阶段路由到 agent 节点。
- **修改文件**：
  - `careercrew_core/supervisor/graph.py`
  - `careercrew_core/supervisor/router.py`
  - `tests/unit/test_supervisor_router.py`
- **实现类/函数**：
  - `build_graph(checkpointer) -> CompiledGraph`
  - `route(state) -> str`（阶段+意图 -> agent 名）
- **验收标准**：golden_routes.json 中用例路由正确。
- **测试方法**：`pytest -q tests/unit/test_supervisor_router.py`。

### B4：agent 节点基类
- **目标**：定义 `BaseAgent`，套 ReAct 循环，产出格式化结果。
- **修改文件**：
  - `careercrew_core/agents/base_agent.py`
  - `tests/unit/test_base_agent.py`
- **实现类/函数**：
  - `BaseAgent.run(state) -> state_update`（读 prompt + 套 ReactLoop + 写 agent_outputs）
- **验收标准**：Mock agent 可被 supervisor 调用并返回结构化产出。
- **测试方法**：`pytest -q tests/unit/test_base_agent.py`。

### B5：基础工具注册表 + 1 个内部工具 stub
- **目标**：实现统一工具注册表（schema + requires_confirmation），含 1 个 stub 工具。
- **修改文件**：
  - `careercrew_core/tools/registry.py`
  - `careercrew_core/tools/internal/memory_search.py`（stub）
  - `tests/unit/test_tool_registry.py`
- **实现类/函数**：
  - `ToolRegistry.register(tool)` / `get(name)` / `list_schemas()`
  - `requires_confirmation` 字段标记
- **验收标准**：工具统一 schema；高风险工具可被识别。
- **测试方法**：`pytest -q tests/unit/test_tool_registry.py`。

---

## 阶段 C：3 层记忆 + append-only 树（目标：记忆系统基础版）

### C1：记忆核心数据类型
- **目标**：定义全链路复用的记忆数据结构。
- **修改文件**：
  - `careercrew_core/memory/types.py`
  - `tests/unit/test_memory_types.py`
- **实现类/函数**：
  - `MemoryEntry(id, parentId, type, ts, content)`
  - `TreeNode`（树节点）
  - `UserModel(profile, target_companies, preferences, interview_mastery)`
- **验收标准**：可序列化；字段稳定；事件类型与 metadata 字段对齐 §3.3.6 事件契约（L2/L3 数据契约，只增不改）。
- **测试方法**：`pytest -q tests/unit/test_memory_types.py`。

### C2：情景记忆 append-only JSONL + parentId 树
- **目标**：实现 append-only 写入与 parentId 树结构。
- **修改文件**：
  - `careercrew_core/memory/episodic.py`
  - `tests/unit/test_episodic_memory.py`
- **实现类/函数**：
  - `EpisodicMemory.write(entry)`（append JSONL，自动 id+parentId）
  - `EpisodicMemory.get(id)` / `children(id)`
- **验收标准**：append-only 不改历史；parentId 链正确。
- **测试方法**：`pytest -q tests/unit/test_episodic_memory.py`。

### C3：从叶子回溯到根重建上下文
- **目标**：给定叶子节点，回溯到根拼接上下文。
- **修改文件**：
  - `careercrew_core/memory/episodic.py`（增 `rebuild_context(leaf_id)`）
  - `tests/unit/test_episodic_rebuild.py`
- **实现类/函数**：
  - `EpisodicMemory.rebuild_context(leaf_id) -> list[MemoryEntry]`
- **验收标准**：回溯链完整、顺序正确。
- **测试方法**：`pytest -q tests/unit/test_episodic_rebuild.py`。

### C4：短期 Context Window 管理
- **目标**：管理 state.messages 的长度（compaction 前的简单截断/管理）。
- **修改文件**：
  - `careercrew_core/memory/short_term.py`
  - `tests/unit/test_short_term.py`
- **实现类/函数**：
  - `ShortTermMemory.append(state, msg)` / `trim(state, max_tokens)`
- **验收标准**：超长时按策略截断且保留最近。
- **测试方法**：`pytest -q tests/unit/test_short_term.py`。

### C5：长期 User Model 结构化读写
- **目标**：实现 User Model 结构化读写与字段约束。
- **修改文件**：
  - `careercrew_core/memory/user_model.py`
  - `careercrew_core/tools/internal/profile_update.py`
  - `tests/unit/test_user_model.py`
- **实现类/函数**：
  - `UserModelStore.load(user_id)` / `save(user_id, model)` / `update(user_id, fields)`
  - `profile_update` 工具（字段约束，非法字段拒绝）
- **验收标准**：结构化更新；非法字段拒绝。
- **测试方法**：`pytest -q tests/unit/test_user_model.py`。

### C6：基础写入触发点
- **目标**：关键事件后写情景记忆。
- **修改文件**：
  - `careercrew_core/tools/internal/memory_write.py`
  - `tests/unit/test_memory_write.py`
- **实现类/函数**：
  - `memory_write` 工具（type + content，写 episodic）
- **验收标准**：面试/投递/offer/匹配事件可写入，parentId 正确。
- **测试方法**：`pytest -q tests/unit/test_memory_write.py`。

---

## 阶段 D：自建 RAG 流水线（目标：BGE-M3 + Contextual Chunking + Hybrid + Rerank 跑通）

### D1：BGE-M3 Embedding + 切分/Contextual Chunking
- **目标**：本地实现 BGE-M3 embedding（dense+sparse+colbert，FlagEmbedding）+ RecursiveCharacterTextSplitter + Contextual Chunking（LLM 给每块生成上下文前置）。
- **修改文件**：
  - `careercrew_ai/embedding/bge_m3_embedding.py`（BaseEmbedding + BGE-M3）
  - `careercrew_ai/splitter/recursive_splitter.py`
  - `careercrew_core/rag/chunking/document_chunker.py`、`contextualizer.py`
  - `careercrew_ai/prompts/contextual_chunking.txt`
  - `tests/unit/test_bge_m3_embedding.py`、`test_contextual_chunking.py`
- **实现类/函数**：
  - `BGEM3Embedding(BaseEmbedding).encode(texts) -> (dense, sparse, colbert)`（一次前向三路输出）
  - `Contextualizer.contextualize(chunk, doc) -> str`（调 LLM 生成 50-100 token 上下文前置）
- **验收标准**：BGE-M3 三路输出维度正确；Contextual Chunking 产出带上下文的块（Mock LLM）。
- **测试方法**：`pytest -q tests/unit/test_bge_m3_embedding.py tests/unit/test_contextual_chunking.py`。

### D2：Milvus 后端（BaseVectorStore 实现）
- **目标**：在 `careercrew_ai/vector_store/milvus_store.py` 实现 `MilvusStore`，满足 `BaseVectorStore` 契约，支持 BGE-M3 dense+sparse 混合检索。
- **修改文件**：
  - `careercrew_ai/vector_store/milvus_store.py`
  - `careercrew_ai/vector_store/vector_store_factory.py`（注册 milvus 路由）
  - `tests/integration/test_milvus_backend.py`
- **实现类/函数**：
  - `MilvusStore(BaseVectorStore)`：`upsert` / `query` / `delete_by_metadata` / `get_by_ids`
  - 支持 Dense + Sparse 混合检索（Milvus 原生 BGE-M3 hybrid）
- **验收标准**：upsert -> query roundtrip 确定性；collection 隔离；**Windows 下 milvus-lite 不可安装时，改 `chroma` 后端跑通同一 roundtrip（与 D5 合并验证）**。
- **测试方法**：`pytest -q tests/integration/test_milvus_backend.py`（真实 milvus-lite）。

### D3：Hybrid Search + RRF + Rerank 编排
- **目标**：实现 Hybrid 检索（BGE-M3 dense + sparse 并行召回 + RRF 融合）+ Rerank 编排（硅基流动 rerank API，None 回退）。
- **修改文件**：
  - `careercrew_core/rag/retrieval/hybrid_search.py`、`fusion.py`
  - `careercrew_core/rag/rerank.py`
  - `careercrew_ai/reranker/siliconflow_reranker.py`（BaseReranker + 硅基流动 rerank API）
  - `tests/unit/test_hybrid_search_rrf.py`
- **实现类/函数**：
  - `HybridSearch.search(query, top_k) -> list[Chunk]`（dense+sparse 召回 + RRF）
  - `RRFFusion.fuse(dense_results, sparse_results) -> ranked`（`1/(k+rank)` 加权）
  - `Reranker.rerank(query, candidates) -> ranked`（调硅基流动 rerank API；超时/失败回退 None）
- **验收标准**：RRF 融合分数计算正确且确定性；Rerank 失败回退原排序。
- **测试方法**：`pytest -q tests/unit/test_hybrid_search_rrf.py`。

### D4：rag_query 工具 + 知识库 ingestion pipeline
- **目标**：封装自建 RAG 为 `rag_query` 工具；实现 Ingestion pipeline 摄取知识库到 Milvus（collection `careercrew_kb`）。
- **修改文件**：
  - `careercrew_core/tools/internal/rag_query.py`
  - `careercrew_core/rag/loaders/`（PDF/Word/Markdown 多格式加载）
  - `careercrew_core/rag/pipeline.py`（load->split->contextualize->embed->upsert）
  - `scripts/ingest_knowledge.py`
  - `data/knowledge/`（样例文档）
  - `tests/unit/test_rag_query_tool.py`
- **实现类/函数**：
  - `rag_query(query, top_k, collection) -> list[Chunk]`（调 HybridSearch + Rerank）
  - `IngestionPipeline.run(source_path, collection)`（编排 load + chunking + contextual + BGE-M3 编码 + Milvus upsert）
- **验收标准**：PDF/Markdown/Word 文档可加载并摄取；八股/面经/JD/简历范本样例可摄取并检索；rag_query 返回结构化结果。
- **测试方法**：`pytest -q tests/unit/test_rag_query_tool.py` + 手动跑 `python scripts/ingest_knowledge.py`。

### D5：配置切换 milvus/chroma 验证
- **目标**：验证 milvus/chroma 配置切换零代码。
- **修改文件**：
  - `tests/integration/test_vector_store_switch.py`
- **实现类/函数**：无。
- **验收标准**：改 backend 配置即可切换，roundtrip 均通过。
- **测试方法**：`pytest -q tests/integration/test_vector_store_switch.py`。

---

## 阶段 E：职位匹配官（目标：第一个 agent 落地）

### E1：job_matcher system prompt
- **目标**：编写职位匹配官的 system prompt。
- **修改文件**：`careercrew_ai/prompts/job_matcher.txt`
- **验收标准**：prompt 明确角色、工具使用指引、产出格式。
- **测试方法**：人工 review。

### E2：接 mcp-jobs 工具（mock 先行）
- **目标**：先落地 mock JD 工具（`mock_jobs`）保证 E3/E4 不依赖外部 server；真实 mcp-jobs 接入为可选增量。
- **修改文件**：
  - `careercrew_core/tools/mcp/mock_jobs.py`（MVP：样例 JD 提供方）
  - `careercrew_core/tools/mcp/mcp_client.py`（可选：真实 server 发现注册）
  - `tests/unit/test_mcp_client.py`
- **实现类/函数**：`MockJobs.search(query) -> list[Job]`；`McpClient.discover()` / `register(registry)`（可选）
- **验收标准**：E3/E4 用 mock JD 可跑通；真实 mcp-jobs 若接入，工具可被发现注册（Mock MCP server 单测）。
- **测试方法**：`pytest -q tests/unit/test_mcp_client.py`。

### E3：JD 检索 + 匹配打分
- **目标**：实现 JD-画像匹配打分逻辑。
- **修改文件**：
  - `careercrew_core/agents/job_matcher.py`
  - `tests/unit/test_job_matcher.py`
- **实现类/函数**：`JobMatcher.run(state)`（搜 JD + 打分 + 排序）
- **验收标准**：Mock JD 库下打分排序合理。
- **测试方法**：`pytest -q tests/unit/test_job_matcher.py`。

### E4：命中写入候选池（情景记忆）
- **目标**：匹配命中写 `job_match` 事件到情景记忆。
- **修改文件**：`careercrew_core/agents/job_matcher.py`（调 memory_write）
- **验收标准**：命中后情景记忆有 `job_match` 条目。
- **测试方法**：集成测试。

### E5：单元/集成测试
- **目标**：补齐 job_matcher 的集成测试（supervisor -> matcher -> 工具 -> 记忆）。
- **修改文件**：`tests/integration/test_job_matcher_flow.py`
- **验收标准**：整条链路跑通。
- **测试方法**：`pytest -q tests/integration/test_job_matcher_flow.py`。

---

## 阶段 F：简历顾问（目标：第二个 agent + RAG 简历定制）

### F1：resume_advisor system prompt
- **修改文件**：`careercrew_ai/prompts/resume_advisor.txt`
- **验收标准**：prompt 明确按 JD 定向定制简历的指引。

### F2：简历范本 RAG 检索
- **目标**：用 rag_query 检索简历范本。
- **修改文件**：`careercrew_core/agents/resume_advisor.py`
- **验收标准**：能检索到相关简历范本（Mock）。

### F3：简历定制生成（JD 定向）
- **目标**：按 JD 定制简历。
- **修改文件**：`careercrew_core/agents/resume_advisor.py`
- **实现类/函数**：`ResumeAdvisor.run(state)` -> 简历草稿
- **验收标准**：产出结构化简历草稿。

### F4：简历匹配度评估
- **目标**：集成 Ragas 评估简历-JD 匹配度。
- **修改文件**：`careercrew_core/agents/resume_advisor.py`（调 evaluator）
- **验收标准**：输出匹配度分数。

### F5：测试
- **修改文件**：`tests/unit/test_resume_advisor.py`、`tests/integration/test_resume_flow.py`
- **验收标准**：单元+集成通过。

---

## 阶段 G：CLI + M1 闭环（目标：部分求职闭环可跑通）

### G1：CLI 渲染层
- **目标**：实现 CLI 对话渲染与 HITL 提示。
- **修改文件**：
  - `careercrew_ui/cli/renderer.py`
  - `tests/unit/test_cli_renderer.py`
- **实现类/函数**：`Renderer.render_message()` / `prompt_hitl(action)`
- **验收标准**：agent 输出与 HITL 提示正确渲染。

### G2：工作流编排（意向->匹配->简历 部分闭环）
- **目标**：job_cycle.py 实现阶段流转（intent->planning->match->resume）。
- **修改文件**：
  - `careercrew_cli/workflow/job_cycle.py`
  - `tests/integration/test_match_resume_loop.py`
- **实现类/函数**：`JobCycle.run(intent)` -> 流转至简历
- **验收标准**：意向输入 -> 画像 -> 匹配 -> 简历草稿 链路跑通。

### G3：HITL 基础确认
- **目标**：CLI yes/no 确认基础。
- **修改文件**：`careercrew_cli/hitl/gates.py`
- **实现类/函数**：`confirm(action) -> bool`
- **验收标准**：可确认/拒绝。

### G4：M1 端到端冒烟
- **目标**：M1 闭环 E2E。
- **修改文件**：`tests/e2e/test_match_resume_loop.py`
- **验收标准**：E2E 通过。

---

## 阶段 H：面试官 + 情景记忆（目标：面试模拟 + 记忆写入）

### H1：interviewer system prompt
- **修改文件**：`careercrew_ai/prompts/interviewer.txt`

### H2：出题（基于 JD + 八股）
- **目标**：rag_query 检索面经/八股，结合 JD 出题。
- **修改文件**：`careercrew_core/agents/interviewer.py`
- **验收标准**：出题相关、有难度梯度。

### H3：模拟问答 + 评分
- **修改文件**：`careercrew_core/agents/interviewer.py`
- **实现类/函数**：`Interviewer.run(state)`（出题->问答->评分循环）
- **验收标准**：问答循环 + 评分产出。

### H4：面试记录写情景记忆
- **修改文件**：`careercrew_core/agents/interviewer.py`（写 interview_qa + 向量）
- **验收标准**：面试结束写 `interview_qa` 事件 + Milvus 向量。

### H5：测试
- **修改文件**：`tests/unit/test_interviewer.py`、`tests/integration/test_interview_sim.py`
- **验收标准**：单元+集成通过。

---

## 阶段 I：记忆按需检索 + compaction 基础版（目标：记忆主动检索 + 压缩）

### I1：memory_search 主动检索
- **目标**：实现 memory_search 工具，Milvus 语义检索情景记忆。
- **修改文件**：
  - `careercrew_core/memory/vector_index.py`
  - `careercrew_core/tools/internal/memory_search.py`（补全）
  - `tests/unit/test_memory_search.py`
- **实现类/函数**：`memory_search(query, top_k) -> list[MemoryEntry]`
- **验收标准**：检索情景记忆 top_k 命中相关。

### I2：compaction 触发（token 占比，真实 usage）
- **目标**：用模型真实 usage token 数触发 compaction。
- **修改文件**：`careercrew_core/memory/compaction.py`
- **实现类/函数**：`should_compact(state) -> bool`（基于真实 usage）
- **验收标准**：超阈值触发。

### I3：保留区 + 压缩区分块总结
- **修改文件**：`careercrew_core/memory/compaction.py`
- **实现类/函数**：`compact(state) -> state`（保留区原封 + 压缩区分块总结合并）
- **验收标准**：保留区完整，压缩区被总结替代。

### I4：compaction 条目写 JSONL（firstKeptEntryId）
- **修改文件**：`careercrew_core/memory/compaction.py`（写 compaction 条目）
- **验收标准**：compaction 条目带 `firstKeptEntryId`。

### I5：测试
- **修改文件**：`tests/unit/test_compaction.py`
- **验收标准**：压缩无损性断言（关键信息不丢）。

---

## 阶段 J：谈判师 + 规划师（目标：补齐 5 agent）

### J1：salary_negotiator prompt + 策略
- **修改文件**：`careercrew_ai/prompts/salary_negotiator.txt`、`careercrew_core/agents/salary_negotiator.py`
- **验收标准**：产出谈薪策略与话术草稿。

### J2：公司/薪资公开数据检索
- **修改文件**：`careercrew_core/agents/salary_negotiator.py`（rag_query + Google MCP）
- **验收标准**：检索薪资数据辅助策略。

### J3：career_planner prompt + 画像 + 目标公司池
- **修改文件**：`careercrew_ai/prompts/career_planner.txt`、`careercrew_core/agents/career_planner.py`
- **实现类/函数**：`CareerPlanner.run(state)`（建画像 + 目标公司池）
- **验收标准**：更新 User Model + 目标公司池。

### J4：测试
- **修改文件**：`tests/unit/test_negotiator.py`、`tests/unit/test_planner.py`
- **验收标准**：单元通过。

---

## 阶段 K：HITL 接工具层（目标：高风险闸门落地）

### K1：工具 requires_confirmation 标记
- **修改文件**：`careercrew_core/tools/registry.py`（标记 submit_application/send_greeting/accept_offer/salary_talk_script）
- **验收标准**：高风险工具标记正确。

### K2：LangGraph interrupt 集成
- **修改文件**：`careercrew_core/supervisor/hitl.py`
- **实现类/函数**：`interrupt_for_confirmation(action)` / `resume(decision)`
- **验收标准**：interrupt 暂停 + 恢复正确。

### K3：投递/打招呼/接 offer 闸门
- **修改文件**：`careercrew_cli/hitl/gates.py`
- **验收标准**：四类闸门均触发确认。

### K4：测试
- **修改文件**：`tests/integration/test_hitl_flow.py`
- **验收标准**：HITL 触发正确性（高风险必触发、低风险不误触发）。

---

## 阶段 L：评估 + Dashboard（目标：评估闭环 + 可视化）

### L1：答案级评估
- **修改文件**：`careercrew_core/evaluation/answer_eval.py`（自建 CompositeEvaluator）
- **验收标准**：简历匹配度/面试题质量指标输出。

### L2：业务级评估
- **修改文件**：`careercrew_core/evaluation/business_eval.py`（统计情景记忆事件）
- **验收标准**：转化率/通过率/offer 统计。

### L3：自建 trace 全链路打点
- **修改文件**：各 agent / supervisor / memory 模块（注入 trace 打点）
- **验收标准**：agent_loop/hitl/memory_op/compaction trace 落 logs/traces.jsonl。

### L4：Streamlit Dashboard
- **修改文件**：`careercrew_ui/dashboard/`（app + 三页面）
- **验收标准**：总览/数据/追踪三页面可用。

### L5：测试
- **修改文件**：`tests/unit/test_evaluation.py`、`tests/integration/test_dashboard_smoke.py`
- **验收标准**：评估 + Dashboard 冒烟通过。

---

## 阶段 M：高级亮点（选 1-2，目标：理解/能讲/部分实现）

> 从以下挑 1-2 个实现，其余做到"理解 + 能讲"。

### M1：Loop Engineering 七步闭环 + 三角色（选）
- **修改文件**：`careercrew_core/loop/`（新建：七步建模 + Planner/Developer/Reviewer 对位）
- **验收标准**：求职闭环可按七步建模运行；三角色建设性对抗可见。

### M2：Pre-compaction Memory Flush（选）
- **修改文件**：`careercrew_core/memory/compaction.py`（压缩前 flush 重要信息到长期记忆）
- **验收标准**：压缩前先跑一轮 flush，关键信息不丢。

### M3：多 agent 会诊（选）
- **修改文件**：`careercrew_core/supervisor/graph.py`（fan-out + join）
- **验收标准**：同一问题多 agent 并行给意见并综合。

### M4：Agentic RAG（query router + decomposition）（选）
- **修改文件**：`careercrew_core/rag/agent_router.py`、`query_decomposer.py`
- **验收标准**：query router 按意图路由到 KB / web / 记忆；多跳问题分解为子查询并发检索后综合。

### M5：检索自纠正 Self-RAG / CRAG（选）
- **修改文件**：`careercrew_core/rag/retrieval_assessor.py`
- **验收标准**：检索评估器对召回质量打分，差则触发查询改写 / 重试 / web 回退；提升 Grounding。

### M6：层级/图 RAG（RAPTOR 或 LightRAG）（选）
- **修改文件**：`careercrew_core/rag/hierarchical/`（递归抽象树 或 轻量知识图）
- **验收标准**：面经跨文档关联检索；全局性问题可命中。

### M7：Late Chunking / ColBERT 多向量（选）
- **修改文件**：`careercrew_ai/embedding/bge_m3_embedding.py`（colbert 模式）、`careercrew_core/rag/chunking/late_chunker.py`
- **验收标准**：BGE-M3 colbert 多向量 token 级匹配；late chunking 长文档处理。

---

## 阶段 N：自建 MCP + dogfood + 收尾（目标：真实投递 + 拿 offer 验收）

### N1：自建求职者端 MCP
- **目标**：仿 boss-zhipin-mcp，Playwright+CDP 实现投递/进度/面经采集。
- **修改文件**：`careercrew_mcp/`（新建独立包）或 `careercrew_core/tools/mcp/self_built/`
- **验收标准**：MCP Server 可暴露投递/跟踪/采集工具。

### N2：投递/进度跟踪接真实 MCP
- **修改文件**：`careercrew_core/tools/mcp/`（替换 mock_apply）
- **验收标准**：真实投递/跟踪可用。

### N3：dogfood 拿 offer
- **目标**：用自身知识库跑完整求职周期。
- **修改文件**：`tests/e2e/test_dogfood_cycle.py`
- **验收标准**：完整周期 E2E 通过；真实 dogfood 记录。

### N4：README / 文档收口
- **修改文件**：`README.md`（运行说明 + MCP + Dashboard + 面试题 + 简历建议）
- **验收标准**：开箱即用 + 可复现。

### N5：全链路 E2E 验收
- **修改文件**：`tests/e2e/`（4 个关键 E2E 全绿）
- **验收标准**：match_resume / interview / apply_hitl / dogfood 全绿。

---

## 7. 可扩展性与未来展望

### 短期扩展（MVP 完成后）
- **更多 agent**：HR 跟进 agent、背调准备 agent。
- **更多知识库**：按公司/岗位细分 collection。
- **Dashboard 增强**：求职阶段看板、转化率趋势图。

### 高级方向落地（M-N 之后）
- **Hermes 完整记忆**：Skill Library + 反思自进化。
- **轨迹级评估**：LLM-as-judge + 黄金回放。
- **Delegate 三级授权**：细化闸门。
- **Hooks 统一接口**：before_tool_call / before_model / before_compaction / after_compaction。
- **事件驱动 + 单向依赖**：一套 core 配 CLI + Dashboard 双前端。

### 长期愿景
- **多用户**：checkpointer 换 Postgres、User Model 换 DB。
- **云端部署**：Milvus Docker/K8s、API 化。
- **求职知识库沉淀**：从代码 -> 八股 -> 面试技巧，形成完整求职知识库，反哺社区。

---

## 8. 面试考点与简历亮点映射

> "教是最好的学"--每个模块对应的高频面试题与简历 bullet，开发时同步整理。配套 skill：`interview-prep`（模拟面试）/ `resume-writer`（写简历）/ `project-review`（复习）/ `project-learner`（知识点学习）。

| 模块 | 高频面试题 | 简历亮点 bullet |
|------|-----------|----------------|
| 多 Agent 编排 | LangGraph supervisor 怎么路由？为什么不纯 LangGraph？checkpointer 存什么？多 agent 会诊怎么做？ | 设计 5 agent + supervisor 状态机路由，9 阶段求职闭环可 dogfood |
| 手写 ReAct | 为什么不用 create_react_agent？怎么判 tool_call？轮次上限？每轮上下文怎么组装？ | 手写可见 ReAct 循环，工具推理过程全链路 trace 可回放，不依赖黑盒 |
| 三层记忆 | append-only 树解决什么？回溯算法复杂度？compaction 怎么触发/防丢？ | 仿 Hermes 三层记忆，append-only 树支持黄金轨迹回放与轨迹级评估 |
| BGE-M3 RAG | 三路输出怎么拿？为什么本地跑？sparse vs BM25 区别？colbert 代价？ | 自建 RAG：BGE-M3 三合一 + Contextual Chunking，检索失败率降 49% |
| Hybrid+RRF | RRF 公式？为什么用排名倒数不用分数？top_k 怎么定？ | Hybrid 检索 + RRF 融合 + bge-reranker 精排，两段式架构平衡查准与查全 |
| 文档加载 | 为什么用 MarkItDown？多格式怎么统一？BaseLoader 怎么抽象？ | 多格式文档加载（PDF/Word/Markdown）统一转 Markdown，MarkItDown + BaseLoader 可插拔 |
| Milvus 可插拔 | BaseVectorStore 怎么抽象？milvus-lite vs Docker？collection 隔离？ | 自建 Milvus 后端 + Chroma 兜底，配置驱动零代码切换向量库 |
| HITL 闸门 | interrupt 怎么恢复状态一致？哪些动作必确认？Delegate 三级？ | 高 stakes 决策默认 HITL，LangGraph interrupt 实现投递/接 offer 闸门 |
| 工具层 | MCP 与内部函数怎么统一？requires_confirmation 怎么标记？ | 统一工具注册表，MCP+内部函数同 schema，风险分级触发 HITL |
| 评估 | 答案级 vs 业务级 vs 轨迹级？业务数据从哪来？黄金回放？ | 答案级(Ragas)+业务级(转化率)+轨迹级(黄金回放) 三层评估闭环 |
| 可观测 | 为什么不用 LangSmith？trace schema？怎么定位坏 case？ | 自建全链路 trace(JSON Lines)+Streamlit Dashboard，零外部依赖可观测 |
| 工程化 | 四层依赖方向？TDD 分层？conda env？CI？ | 四层单向依赖架构 + TDD 分层测试，单元覆盖≥80% |

> 每完成一个模块：用 `project-review` / `project-learner` 自测掌握度，用 `resume-writer` 沉淀简历 bullet，用 `interview-prep` 模拟面试。

---

## 9. 快速开始

> 开发/运行速查。自动开发直接说 `auto code`，auto-coder skill 走"同步 spec -> 找任务 -> 实现 -> 测试 -> 持久化"流水线。

### 9.1 环境准备

```bash
# conda env careercrew（Python 3.12，已建好）
conda activate careercrew
# BGE-M3 模型已下至 data/ms_cache/（ModelScope，HF 直连被拦）
# 模型路径: data/ms_cache/models/BAAI--bge-m3/snapshots/master
```

### 9.2 配置

```bash
# 1. 设硅基流动 API key（环境变量，不硬编码）
export SILICONFLOW_API_KEY="sk-xxx"            # Git Bash
# $env:SILICONFLOW_API_KEY="sk-xxx"            # PowerShell

# 2. 编辑 config/settings.yaml（见 §5.5 完整配置示例）
#    关键：llm.base_url 指向硅基流动、embedding.provider=bge_m3_local、rerank.backend=siliconflow
```

### 9.3 运行

```bash
conda run -n careercrew python -m careercrew_cli.app          # CLI 求职顾问
conda run -n careercrew python scripts/start_dashboard.py     # Streamlit Dashboard
conda run -n careercrew python scripts/ingest_knowledge.py data/knowledge/   # 知识库摄取
```

### 9.4 测试

```bash
conda run -n careercrew pytest -q tests/unit/         # 单元（秒级）
conda run -n careercrew pytest -q tests/integration/  # 集成（多组件协作）
conda run -n careercrew pytest -q tests/e2e/          # 端到端（求职闭环）
```

### 9.5 自动开发（auto-coder）

```bash
# 说 "auto code" -> 自动找下一个待办任务并实现
# 说 "auto code A1" -> 指定任务
# 说 "auto code --no-commit" -> 跑完不 commit
```

> 所有 python/pytest 命令都在 conda env `careercrew` 下（`conda activate careercrew` 或 `conda run -n careercrew ...`）。

---

> **文档状态**：v0.3（2026-08-01 修订）——LangGraph 1.x 版本对齐（§3.1.6）、HITL interrupt 恢复语义（§3.8.2）、记忆事件契约（§3.3.6）、知识库数据源与 MCP mock 先行落地（§3.6/§3.7）、配置同步（`rag.loaders`）、CI 与覆盖率口径、Milvus Lite Windows 风险、多用户边界。后续按实际开发迭代细化（排期子任务的修改文件列表与验收标准随实现校正）。
> **决策记录**：见 `prompts/gen_dev_spec.md` 末尾"决策记录"小节（供参考，不写进 spec）。
