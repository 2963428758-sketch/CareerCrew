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

#### 3.3.6 高级方向【高级方向】
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
- **高风险拦截**：执行前检查 `requires_confirmation`，若为 true 则抛 `Interrupt` 信号给 supervisor，走 HITL。

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
| **milvus-lite** | 本地开发、MVP | 嵌入式，`pip install pymilvus` 即用，零外部服务 |
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

#### 3.6.1 现成 MCP 接入【MVP 核心】
- **mcp-jobs**：职位检索（JD 库）。
- **Google MCP**：通用搜索（公司信息、薪资公开数据补充）。
- 通过 MCP client 连接，工具自动注册进统一工具注册表。

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
| Chunking | RecursiveCharacterTextSplitter + **Contextual Chunking** | `careercrew_core/rag/chunking/` | Markdown 感知切分；每块调 LLM 生成 50-100 token 上下文前置再索引（Anthropic Contextual Retrieval，减 49% 检索失败） |
| Embedding | **BGE-M3**（dense + sparse + ColBERT） | `careercrew_ai/embedding/` | 一模型三路输出，中文 100+ 语言，8192 token，本地 sentence-transformers；稀疏路免额外 BM25 索引 |
| 检索 | Hybrid（BGE-M3 dense + sparse）+ RRF 融合 | `careercrew_core/rag/retrieval/` | 两路 RRF 融合，Milvus 原生支持 BGE-M3 混合检索 |
| Rerank | **硅基流动 rerank API**（bge-reranker-v2-m3） | `careercrew_ai/reranker/` | cross-encoder 中文重排，低频走 API；可关（None）回退 |
| 向量库 | Milvus Lite + Chroma 兜底 | `careercrew_ai/vector_store/` | 见 3.5 |

#### 3.7.2 设计亮点
- **BGE-M3 三合一 > 分离的 BM25+Embedding**：一次前向同时得 dense/sparse/colbert，稀疏路无需维护倒排索引，与 Milvus 原生混合检索直接对接。
- **Contextual Chunking**：ingestion 阶段用 LLM 给每块生成文档级上下文前置，解决"块脱离上下文难检索"问题；用 prompt caching 控成本。
- **可插拔**：Embedding/Rerank/VectorStore 均为 `Base*` 抽象 + 工厂，配置切换（如换 OpenAI embedding、Cohere rerank）零代码。

#### 3.7.3 知识库 Ingestion
自建 Ingestion Pipeline 摄取知识库到 Milvus（collection `careercrew_kb`）：
- 大模型八股 + 真实面试题
- 算法岗面经
- JD 库（mcp-jobs 沉淀）
- 公司/薪资公开数据
- 简历范本

流水线：Loader -> Splitter -> Contextual Chunking（LLM 加上下文）-> BGE-M3 编码（dense+sparse）-> Milvus Upsert。

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

#### 3.8.2 Delegate 三级授权【高级方向】
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
| AI 层 | `careercrew_ai` | 自建 `llm_factory`/embedding(BGE-M3)/rerank/vector_store；手写 ReAct 内核；agent prompts |
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

---
