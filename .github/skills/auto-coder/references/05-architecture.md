## 5. 系统架构与模块设计

### 5.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          前端层 (React Web / FastAPI API)                    │
│                                                                             │
│    ┌──────────────────────┐              ┌──────────────────────┐           │
│    │   web/ (React SPA)   │              │  careercrew_api       │           │
│    │  求职对话/会诊/面试等 │              │  SSE 流式 + 记忆/线程  │           │
│    └──────────┬───────────┘              └──────────┬───────────┘           │
│               │      HTTP / SSE       调用核心层       │                    │
└───────────────┼───────────────────────────────────────┼─────────────────────┘
                │                                       │
                ▼                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              careercrew_core - 工作流 + HITL + 编排 + Agent                  │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    求职周期工作流编排 (workflow/job_cycle.py)          │  │
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
│                      │ │ + Qdrant            │ │  Postgres 记忆库         │
└──────────────────────┘ └─────────────────────┘ │  LangSmith               │
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
├── careercrew_core/workflow/            # 求职周期工作流闭环（原 CLI 版迁移）
│   ├── __init__.py
│   └── job_cycle.py                    # intent->...->review->循环 编排（API 复用）
│
├── careercrew_api/                      # API 层（FastAPI + SSE + 记忆/线程管理）
│   ├── __init__.py
│   ├── main.py                         # 应用工厂 + /api 挂载 + 托管 web/dist
│   ├── runtime.py                      # 重组件单例 + 会话级 agent/JobCycle 工厂
│   ├── routers/                        # data/chat/interview/resume/consult/knowledge
│   └── schemas.py                      # pydantic 请求/响应模型
│
├── web/                                 # 前端（React + Vite SPA）
│   ├── src/pages/                      # Chat/Consult/Interview/Resume/Knowledge/Data
│   ├── src/store/                      # chatStore / threadStore（zustand）
│   └── src/components/                 # 通用 UI 组件
│
├── config/                              # 配置文件
│   └── settings.yaml                    # 主配置（agent prompts 唯一位置：careercrew_ai/prompts/）
│
├── data/                                # 数据目录
│   ├── db/
│   │   ├── milvus/                      # Milvus Lite 嵌入式（KB + 情景记忆向量）
│   │   ├── checkpointer.db              # LangGraph SQLite checkpointer
│   │   └── (chroma 兜底目录)
│   └── knowledge/                       # 知识库原始文档（八股/面经/JD/简历范本）
│
├── logs/                                # 日志
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
│   ├── cleanup_old_memory.py            # 旧记忆数据清理（一次性迁移）
│   └── eval_langsmith.py                # LangSmith 评估
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

#### 5.3.3 工作流 (`careercrew_core/workflow`)

| 模块 | 职责 | 关键技术点 |
|------|------|-----------|
| `workflow/job_cycle.py` | 求职周期闭环编排 | 阶段流转 + 循环陪跑 |

#### 5.3.4 API 层 (`careercrew_api`) 与前端 (`web/`)

| 模块 | 职责 | 关键技术点 |
|------|------|-----------|
| `runtime.py` | 重组件单例 + 会话工厂 | LLM/RAG/记忆/agent 组装 |
| `routers/data.py` | 画像/记忆/线程/设置 API | Postgres 记忆 + 治理开关 |
| `web/src/pages/DataPage.tsx` | 数据看板 | 画像 / 记忆管理 / 记忆设置 |

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

langsmith:
  enabled: true                  # LangSmith 全链路追踪（替代自建 trace）
  project: careercrew
  api_key: "${LANGSMITH_API_KEY}"
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
| LLM | API key 错 / 余额不足 / 模型名不存在 | A3 配置校验只做 key 非空等静态检查（`create_llm` 构造不触网）；模型名 / 余额 / 连通性探活由 `careercrew_api/runtime.py` 初始化探活；首次 invoke 前的运行时错误按"重试 → 可读错误"处理 |
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
