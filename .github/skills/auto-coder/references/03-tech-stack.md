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

---

### 3.8 HITL 闸门【MVP 核心 - 基础】+【高级方向 - Delegate 三级授权】

**目标：** 高 stakes 决策必人工确认；高级方向细化授权粒度。

#### 3.8.1 基础 HITL【MVP 核心】
- **机制**：LangGraph `interrupt`。工具标 `requires_confirmation=true` 时，supervisor 暂停图执行，等待人工确认（Web 确认 / 修改）后恢复。
- **必确认动作**：
  - 投递简历（`submit_application`）
  - 打招呼（`send_greeting`）
  - 接 offer（`accept_offer`）
  - 谈薪话术（`salary_talk_script`）
- **恢复**：人工可确认 / 拒绝 / 修改后确认，结果写回 state 与情景记忆。

#### 3.8.2 interrupt 恢复语义【MVP 核心】

> ReAct 循环内触发 HITL 的实现约束（B2 / K2 落地，langgraph 1.x）：

- **挂起**：agent 的工具执行器发现 `requires_confirmation=true` 时**不执行工具**，调用节点内 `interrupt()` 挂起整个图，payload = 待确认动作（工具名 + 参数 + 风险说明）。Web 通过 SSE 收到 `__interrupt__` 事件后渲染确认 UI；**等待输入期间图处于挂起状态，不阻塞线程**。
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

**目标：** LangSmith 全链路追踪 + React Web 数据看板。

#### 3.11.1 全链路 Trace【MVP 核心】
- LangSmith 追踪：LLM/工具/ReAct/HITL/RAG/记忆全链路，默认脱敏上传（`careercrew_core/tracing/langsmith.py`）。
- 逐轮明细直接在 LangSmith 控制台查看，无自建 trace schema。

#### 3.11.2 Web 数据看板【MVP 核心】
`web/src/pages/DataPage.tsx`：
- **画像**：用户能力画像 / 求职偏好（可编辑，写入语义记忆）。
- **记忆**：语义事实 + 情景事件浏览 / 删除。
- **记忆设置**：全局开关 + 用户级 enabled/generate/use 策略。

---

### 3.12 分层目录结构【MVP 核心】

三层包组织 + 独立 Web 前端，单向依赖（core 只发事件不碰渲染）：

| 层 | 包名 | 职责 |
|----|------|------|
| AI 层 | `careercrew_ai` | LLM 适配 / embedding(BGE-M3) / reranker / vector_store / `create_agent` 执行链 / prompts |
| 核心层 | `careercrew_core` | LangGraph supervisor + 6 agent 节点 + 记忆 + 工具注册表 + state + RAG + 求职周期工作流 |
| API 层 | `careercrew_api` | FastAPI（SSE 流式 / 会诊 / 记忆与线程管理），生产托管 `web/dist` |
| 前端 | `web/` | React + Vite SPA（求职对话 / 会诊 / 面试 / 简历 / 知识库 / 数据） |

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
- **事件驱动 + 单向依赖**：core 只跑逻辑发事件不碰渲染，FastAPI 提供 API，React Web 独立前端。
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
