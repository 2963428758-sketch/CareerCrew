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
| B1 | Thread State 定义 + SQLite checkpointer | [ ] | | CareerCrewState + checkpointer |
| B2 | 手写 ReAct 循环内核（可见 while） | [ ] | | react_loop.py + 轮次上限 |
| B3 | LangGraph supervisor 骨架（路由） | [ ] | | graph.py + router.py |
| B4 | agent 节点基类（套 ReAct） | [ ] | | base_agent.py |
| B5 | 基础工具注册表 + 1 个内部工具 stub | [ ] | | registry.py + memory_search stub |

#### 阶段 C：3 层记忆 + append-only 树

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| C1 | 记忆核心数据类型（MemoryEntry/TreeNode/UserModel） | [ ] | | memory/types.py |
| C2 | 情景记忆 append-only JSONL + parentId 树 | [ ] | | episodic.py |
| C3 | 从叶子回溯到根重建上下文 | [ ] | | episodic.rebuild_context |
| C4 | 短期 Context Window 管理 | [ ] | | short_term.py |
| C5 | 长期 User Model 结构化读写 | [ ] | | user_model.py + profile_update |
| C6 | 基础写入触发点（面试/投递/offer 后写） | [ ] | | memory_write 工具 |

#### 阶段 D：自建 RAG 流水线

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| D1 | BGE-M3 Embedding + 切分/Contextual Chunking | [ ] | | bge_m3_embedding.py / contextualizer.py |
| D2 | Milvus 后端（BaseVectorStore 实现） | [ ] | | milvus_store.py（CareerCrew 自有） |
| D3 | Hybrid Search + RRF + Rerank 编排 | [ ] | | hybrid_search.py / fusion.py / rerank.py |
| D4 | rag_query 工具 + 知识库 ingestion pipeline | [ ] | | rag_query.py / pipeline.py / ingest_knowledge.py |
| D5 | 配置切换 milvus/chroma 验证 | [ ] | | 工厂路由 roundtrip 测试 |

#### 阶段 E：职位匹配官

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| E1 | job_matcher system prompt | [ ] | | prompts/job_matcher.txt |
| E2 | 接 mcp-jobs 工具 | [ ] | | MCP client 发现注册 |
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
| 阶段 B | 5 | 0 | 0% |
| 阶段 C | 6 | 0 | 0% |
| 阶段 D | 5 | 0 | 0% |
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
| **总计** | **65** | **4** | **6%** |

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
- **验收标准**：可序列化；字段稳定。
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
- **验收标准**：upsert -> query roundtrip 确定性；collection 隔离。
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

### E2：接 mcp-jobs 工具
- **目标**：MCP client 发现并注册 mcp-jobs。
- **修改文件**：
  - `careercrew_core/tools/mcp/mcp_client.py`
  - `tests/unit/test_mcp_client.py`
- **实现类/函数**：`McpClient.discover()` / `register(registry)`
- **验收标准**：mcp-jobs 工具可被发现注册（Mock MCP server）。
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
