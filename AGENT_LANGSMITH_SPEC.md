# 统一实施规格：LangChain 1.x Agent 执行链迁移 + LangSmith 全链路追踪

> 本文档合并两个工作流（Part A：Agent 执行链迁移；Part B：LangSmith 数据追踪），
> 因为它们共享改动面（BaseAgent / ReactLoop / runtime / settings / tests），合并为一次迭代落地。
> 前置条件：多模态 RAG 改造（`MULTIMODAL_RAG_SPEC.md`）先提交——工作区已有未提交实现，
> 本规格的改动在其之上叠加。

## 0. 背景、范围与主路径

**现状盘点（自建 vs LangChain）**：

| 层 | 现状 | 本次动作 |
|---|---|---|
| LLM 适配 | 已用 `langchain.chat_models.init_chat_model` | 不动 |
| ReAct 循环 | 自建 `ReactLoop`（手写 while） | 退役，换 `create_agent` |
| 上下文组装 | 自建 `ContextBuilder` | 退役（create_agent 内置 system prompt） |
| 工具层 | `ToolRegistry`/`ToolSpec` 包 langchain `BaseTool` | 保留（薄元数据层） |
| Agent 节点 | `BaseAgent` 包 ReactLoop 作 LangGraph 节点 | 内部换 create_agent，契约不变 |
| Supervisor | LangGraph（已有） | 不动 |
| RAG / 记忆 / 评估 | 自建 | 不动（RAG 为定制多模态管线，已另行 spec） |

**范围决策（已确认）**：

- A：只迁 agent 执行链；RAG 多模态管线、记忆、评估保持自建。
- B：保留对外契约——`last_result.{content, stopped_reason, tool_calls_total, iterations}`，
  runtime / job_cycle / SSE / 前端零改动；逐轮 `ReactIteration` 明细丢弃，详细过程交给 LangSmith。
- HITL：本次不接入 agent 执行流（`requires_confirmation` 工具保持现状），预留 middleware 接缝。
- 主路径：**Web 前端 + FastAPI（SSE 流式）**。CLI 不在验证范围，但保留可运行
  （`test_smoke_imports` 依赖 CLI 入口）。

## Part A — LangChain 1.x Agent 执行链迁移

### A1 目标

用 LangChain 1.x 正统新 API `create_agent`（LangGraph 编译图）替换手写 ReAct 循环，
agent 执行链全部落在 LangChain 平台：LLM 调用、工具调用、循环控制、流式事件由平台提供；
同时为后续 HITL（interrupt）与 LangSmith 追踪（Part B）铺路。

### A2 技术基线（已实测，环境 careercrew）

- langchain 1.3.14 / langchain-core 1.5.3 / langgraph 1.2.10。
- `create_react_agent` 已移除；唯一高层入口
  `create_agent(model, tools, *, system_prompt, middleware, response_format, state_schema, checkpointer, interrupt_before/after, ...)`，
  返回 `CompiledStateGraph`。
- **测试替身必须继承 `BaseChatModel`**：纯鸭子类型（bind_tools/invoke 手写类）在
  create_agent 下抛 `NotImplementedError`；需实现 `_generate`/`_stream` 且
  `bind_tools` 返回 self。
- 流式事件：`agent.stream(input, stream_mode=["messages","updates"])` 产出两类事件——
  `("messages", (AIMessageChunk, metadata))`（token 级，`metadata["langgraph_node"]=="model"`
  为模型文本，tools 节点也会发 ToolMessage 事件）与 `("updates", {node: update})`（节点级完整状态）。
- **recursion_limit 超限不可靠**：实测 langgraph 1.2.10 在超限时抛 `KeyError 'model'`
  （非 `GraphRecursionError`），不能作为稳定信号；max_iterations 用 middleware 实现。

### A3 设计

**A3.1 create_agent 集成**：`BaseAgent.__init__` 编译
`create_agent(model=llm, tools=registry.bindable_tools() or None, system_prompt=..., state_schema=..., middleware=[MaxIterationsMiddleware(...)])`；
`run(state)` 内部驱动该图。`BaseAgent` 类名与 `run(state) -> dict` 契约保留。

**A3.2 状态适配**：自定义 `state_schema`——

```python
class AgentExecState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    _it: NotRequired[int]   # 私有迭代计数通道（middleware 用）
```

`run(state)` 只取 `state["messages"]` 喂图，不要求 CareerCrewState 全字段；
产出照旧走 `_build_update(result)`（`messages` + `agent_outputs{content, stopped_reason, tool_calls_total, iterations}`）。

**A3.3 流式适配**：`run()` 用
`agent.stream({"messages": msgs}, stream_mode=["messages","updates"], config={"recursion_limit": ...})`
同步迭代；`"messages"` 流中 `langgraph_node=="model"` 的文本 chunk 喂现有
`stream_callback`（CLI/SSE 零改动）；tools 节点的 ToolMessage 事件不转发给用户。
`"updates"` 流累积：每个 `{"model": ...}` 事件记一轮迭代；最终 AIMessage 取 `content`；
`ToolMessage` 数记 `tool_calls_total`。

**A3.4 max_iterations**：`MaxIterationsMiddleware`（继承 `AgentMiddleware`）——

- `before_model(state, runtime)`：`_it = state.get("_it", 0) + 1`，返回 `{"_it": _it}`（状态更新）。
- `wrap_model_call(request, handler)`：`request.state["_it"] > max_iters` 时直接返回
  `AIMessage(content="（已达最大迭代轮次）")`（不调模型，agent 循环自然结束）；否则 `handler(request)`。

不依赖 recursion_limit 崩溃路径。`config["recursion_limit"]` 仍设一个安全上限（如
`max_iters*2 + 6`）作为兜底。

**A3.5 stopped_reason 语义**：最后一条 AIMessage 无 tool_calls → `"final_answer"`；
middleware 短路 → `"max_iterations"`；工具执行异常由 ToolNode 默认转
`ToolMessage("Error: ...")` 回喂 LLM（与现状 ReactLoop 一致，不中断循环）。
runtime 的"搜索轮次已达上限"兜底文案依赖 `last_result.stopped_reason`，契约不变，继续生效。

**A3.6 无工具场景**：`tools=None` 时 create_agent 等效单模型节点，`test_base_agent_no_tools`
语义保持。

### A4 测试策略

- 新增测试替身（`tests/` 内公共 fake）：`BaseChatModel` 子类，`bind_tools` 返回 self，
  `_generate` 按预置响应列表出消息，`_stream` 按 chunk 出（可复现现有 FakeChatModel 用例）。
- 用例清单：
  1. tool_call → 工具执行 → 最终答案（断言 messages、AgentResult 字段）；
  2. max_iterations 短路（模型永不停止调工具 → `stopped_reason="max_iterations"`，迭代数正确）；
  3. 无工具直接回答；
  4. 流式 token 回调（`stream_callback` 收到与模型 chunk 一致的内容）；
  5. 工具异常回喂（工具抛错 → ToolMessage Error 回喂，循环继续）；
  6. ToolRegistry 绑定（bindable_tools 直接传入 create_agent）。
- `test_react_loop.py` 的语义并入 `test_base_agent.py`（或改名 `test_agent_execution.py`）；
  其它 agent 单测（job_matcher / resume_advisor / interviewer 等）替换 fake 驱动方式。
- 回归：现有断言 `agent_outputs`、`last_result`、`tool_calls_total`、`iterations` 的用例全部保留原断言。

### A5 落地文件

- 新增：`careercrew_ai/agents/langchain_agent.py`（create_agent 组装 + 流式适配 +
  MaxIterationsMiddleware + AgentResult 计算）；**`AgentResult` 契约迁到这里保留**。
- 修改：`careercrew_core/agents/base_agent.py`（内部换实现；`tracer` 参数移除，与 Part B 一致）。
- 删除：`careercrew_ai/react/react_loop.py`、`careercrew_ai/react/context_builder.py`
  （`ReactLoop`/`ReactIteration`/`ContextBuilder` 退役；`careercrew_ai/react/__init__.py`
  相应清理——目前唯一消费方是 `base_agent.py`）。
- 不动：`careercrew_api/runtime.py` 的对外方法、`careercrew_cli/workflow/job_cycle.py`、
  SSE 桥、前端、ToolRegistry、RAG、记忆。

## Part B — LangSmith 全链路追踪集成（修订版）

> 本部分基于用户的 LangSmith 规格修订：修正 anonymizer 生效机制、SSE 根 run 位置、
> 根 run 预算纪律、追踪范围声明，并去掉 CLI 相关埋点（主路径只有前端）。

### B1 配置与依赖

- `pyproject.toml`：`langsmith>=0.10`（已装 0.10.16；`>=0.1` 太宽，API 变化快）。
- `config/settings.yaml` 新增：

```yaml
langsmith:
  enabled: true
  project: careercrew
  api_key: "${LANGSMITH_API_KEY}"
  masking: true
  max_chars: 2000
```

删除原 `observability` 与 `dashboard` 段；pydantic 模型同步替换。语义校验沿用现有哲学：
`enabled: true` 且 key 缺失/未解析 → fail-fast（`SettingsError`，信息含字段路径）。
**注意：`.env` 当前没有 `LANGSMITH_API_KEY`，合入后首次启动必须先提供 key**；
`.env` 已 gitignore，实现时不回显 key 原文。

### B2 configure_langsmith 与 anonymizer（关键机制）

新建 `careercrew_core/tracing/langsmith.py`：

1. 校验 key、设置环境变量 `LANGCHAIN_TRACING_V2=true`、`LANGCHAIN_PROJECT=careercrew`
   （SDK 的 `get_env_var` namespace 为 LANGSMITH/LANGCHAIN；`get_tracer_project()` 是
   `lru_cache`，必须在首次追踪前设置——`configure_langsmith` 于 `create_llm` 之前调用）。
2. **必须用 `langsmith.run_trees.get_cached_client(api_key=..., anonymizer=...)` 预置缓存**。
   原因（已读源码确认）：`LangChainTracer.__init__` 用 `client or get_client()`，
   `get_client()` 返回 `run_trees.get_cached_client()` 的进程级缓存单例，且**没有公开 setter**；
   `get_cached_client(**kwargs)` 只在**首次调用**时用传入 kwargs 创建。若只建一个独立
   `Client(anonymizer=...)` 实例，LangChain 自动捕获的 LLM/工具 run 走的是无 anonymizer 的
   缓存 client，脱敏不生效。
3. 脱敏策略（anonymizer，入参是 `dict`，需**递归处理所有字符串叶子**）：
   - 字符串超 `max_chars` 截断加 `…[已截断]`；
   - 正则打码：手机号、邮箱、薪资数字（`\d+K`、`\d+-\d+K`、`\d+万`）；
   - 追踪写入失败一律 best-effort，不阻塞主链路。
4. `CareerCrewRuntime._ensure_heavy()` 中于 `create_llm` 之前调用（CLI 不在验证范围，
   不再要求 CLI 侧配置）。

### B3 根 run 纪律（预算与埋点清单）

免费档 5000 traces/月，按"一次用户请求 = 一条根 run"控制。**所有 LLM 调用必须落在某个
根 run 上下文内**，否则自动追踪会把它当成独立根 run。

**根 run（`@traceable(name="careercrew.<endpoint>")`）**：

| 位置 | 说明 |
|---|---|
| `BaseAgent.run` | `@traceable(name="agent.<name>")`，附 `user_id/thread_id/stage` metadata，输出附迭代/工具数/停止原因摘要 |
| `CareerCrewRuntime.run_match_stream` / `run_resume_stream` | **根 run 加在这两个方法上，不是 FastAPI handler**（SSE 端点先返回 `StreamingResponse`，实际工作在线程里异步跑；threading 会复制 contextvars，跨线程追踪成立） |
| `CareerCrewRuntime.consult_stream` | 同上（worker 线程内 agent 与 `_synthesize` 成为子 run） |
| `CareerCrewRuntime.score_answer` | 根 run |
| compaction 的 `Compactor.compact` | 子 run（`@traceable(name="careercrew.compaction")`） |
| ingest 整体（`MultimodalIngestionPipeline.ingest_file/ingest_text`） | 根 run `careercrew.ingest`，**Contextualizer 的逐 chunk LLM 调用必须在其上下文内**，避免批量入库时每 chunk 一条根 run 刷爆配额 |

**游离 LLM 调用清单（必须包裹或纳入上下文）**：runtime 标题生成（`run_match_stream` 内，
随方法级根 run 自动覆盖）、`score_answer`、`consult._synthesize`、
`job_matcher.extract_profile_from_intent`（job_cycle 调用，需包根 run）、
`agent_router.route_llm` / `query_decomposer`（agentic RAG，使用时包根 run）、
`vlm_answer` 回退文本生成、compaction 两处。

**追踪范围声明（v1 明确排除）**：`read_image`、`vlm_answer` 的 VLM 调用、VL reranker
走裸 OpenAI/requests（非 LangChain），LangSmith 不可见——v1 不包（数据不外泄，也不可观测），
如需后续加包 `@traceable`（base64 图片会经过 anonymizer 的 max_chars 截断）。

### B4 读取 API 与前端

- `GET /api/runs?limit=&user_id=&thread_id=&stage=` → `{runs: RunSummary[]}`
  （run_id、name、start/end、duration_ms、status、tokens、estimated_cost——成本按内置价格表，
  未知模型 null；按 metadata 过滤根 run，limit 上限 200）。
- `GET /api/runs/{run_id}` → `{run, steps}`（`read_run(load_child_runs=True)` 展平时间线，
  input/output 预览服务端截断 500 字符）；LangSmith 不可用 → 503 可读错误。
- 删除旧 `GET /api/traces`；前端 `web/src/pages/DataPage.tsx` TracesPanel 改读新接口：
  run 列表卡片（时间/阶段标签/状态/token/成本）+ 点击展开时间线（LLM/工具/agent 步骤、
  耗时、掩码后的输入输出预览）；`types.ts` 新增 `RunSummary/RunStep/RunDetail`。
- `tests/api/conftest.py` 的 FakeRuntime 新增 `list_runs` / `get_run_detail`；
  `test_data_api.py` 的 `test_traces_endpoint` 替换为 `/api/runs` 用例（含 404/503 分支）。

### B5 评估闭环

- 新增 `data/eval/cases.jsonl` 种子用例（3 条 resume_match + 2 条 interview_qa）。
- 新增 `scripts/eval_langsmith.py`：把 `CompositeEvaluator`（resume_match /
  interview_quality）包装为 LangSmith evaluator，注册 dataset、跑用例、以 feedback 回传评分；
  `--business` 模式把 `BusinessEvaluator.stats` 挂到该线程最新 run 的 feedback。
- 新增 `scripts/langsmith_smoke.py`：验证连接、创建合成 run 并回读断言脱敏生效（不启动重栈）。

### B6 迁移与清理

- 删除 `careercrew_core/tracing/trace.py` **及 `careercrew_core/tracing/__init__.py` 的
  `TraceRecorder` 导出**（删文件时同步改，否则 import 断裂）；删除 `tests/unit/test_trace.py`。
- 删除 Streamlit 追踪相关：`careercrew_ui/dashboard/app.py`、`pages/*`；
  `careercrew_ui/dashboard/data.py` 保留（无 streamlit import，`get_traces` 移除）；
  pyproject 的 `ui` optional-dependency 移除。
- `careercrew_cli/app.py` 中 `TraceRecorder` 引用移除（改无 tracer 构造或 no-op），
  保持 CLI 可运行（`test_smoke_imports` 依赖）；CLI 不作为验证目标。
- `logs/traces.jsonl` 停止写入，旧文件归档（logs/ 已在 gitignore）。
- README：新增 `LANGSMITH_API_KEY` 说明；同步更新已过时的 RAG 描述（Milvus/Chroma →
  Qdrant/MinerU 多模态）与 Dashboard 说明（Streamlit → Web 前端）。
- `DEV_SPEC.md` 不改（作为假设记录）。

## Part C — 交互、实施顺序与风险

### C1 两个工作流的依赖关系

- Part A 移除 `BaseAgent`/`ReactLoop` 的 `tracer` 参数，正好满足 Part B 的"ReactLoop 与
  BaseAgent 的 tracer 参数移除"；`@traceable` 加在新的 `BaseAgent.run` 上。
- Part B 的 SSE 根 run 位置（runtime 方法级）与 Part A 的流式适配互不冲突：流式由
  `stream_mode="messages"` 提供 token，追踪由 `@traceable` 提供 run 结构。
- `configure_langsmith` 必须在 `create_llm` 之前、任何 LLM 调用之前执行（`_ensure_heavy` 首部）。

### C2 实施顺序

1. **先提交多模态 RAG 改造**（工作区未提交实现，与本文档共享 runtime/app.py/settings/tests 改动面）。
2. Part A（agent 执行链迁移）——独立可测，先落地并全绿。
3. Part B（LangSmith）——在 A 之上叠加（tracer 参数移除已由 A 完成）。

### C3 风险与回退

| 风险 | 回退 |
|---|---|
| create_agent 行为与手写循环有细微差异（如流式 token 时机） | 测试断言 token 序列与最终 content；异常时回退 `stream_callback` 直通模式 |
| LangGraph 版本升级改变事件/metadata 结构 | 流式适配层单点封装，事件解析隔离在一处 |
| max_iterations middleware 计数与真实迭代不一致 | 单测固定模型永不停止调工具的场景，断言 `_it` 与 ToolMessage 数一致 |
| LangSmith 不可用/key 无效 | 写入静默降级；读取接口 503 可读错误 |
| 5000 条/月配额超限 | 根 run 纪律清单 + ingest 单根 run；必要时降采样（`tracing_sampling_rate`） |
| anonymizer 漏掉嵌套结构 | 递归处理所有字符串叶子 + `langsmith_smoke.py` 回读断言 |

## 合并测试计划

**单元**：
- Part A：agent 执行链（A4 用例清单）、AgentResult 字段、middleware 短路。
- Part B：`test_langsmith_tracer.py`（masking 截断/打码、settings 解析、key 缺失 fail-fast、
  **get_cached_client 预置后自动追踪 run 的 input 被掩码**、run 列表/详情序列化与根 run 过滤，
  mock `langsmith.Client`）；更新 `test_config_loading.py`、`test_react_loop.py`、
  `test_base_agent.py`（移除 tracer 参数）。

**API**：`/api/runs` + `/api/runs/{id}`（FakeRuntime，404/503 分支）；
`test_data_api.py` 的 `/api/traces` 用例替换；dashboard smoke 移除 traces/页面导入断言。

**前端**：`npm run lint` + `npm run build` 通过；手工验证轨迹 tab 列表、展开时间线、
空态与错误态。

**集成（手动，需真实 key）**：`scripts/langsmith_smoke.py` 验证脱敏；
`scripts/eval_langsmith.py` 跑通并在 LangSmith UI 看到 dataset 与 feedback；
真实 match 请求后 `/api/runs` 可见且不含简历全文。

## 假设与默认

- 免费档 5000 traces/月按"一次用户请求=一条根 run"控制，子 run 不额外计费。
- LangSmith 不可用或 key 无效：写入静默降级不阻塞业务；读取接口 503。
- 默认脱敏开启，可经 `settings.yaml` 关闭（完整上传排查用）。
- 主路径为 Web 前端 + API；CLI 保留可运行但不作为验证目标。
- 多模态 RAG 改造先提交；Part A、Part B 同一次迭代落地。
- `DEV_SPEC.md` 不改；`logs/traces.jsonl` 历史文件只归档不删除。
