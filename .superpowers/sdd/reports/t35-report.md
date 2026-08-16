# T3.5 Report — Tool Capabilities + effective_tools 交集 + HITL 拦截

## 状态

**DONE**（两个提交已落地，后端/前端全量绿，foreign hunks 完整保留）。

## 一、审计发现（死者已完成 vs. 遗漏）

### 已完成且正确（死者大部分工作可靠）

| 文件 | 结论 |
|---|---|
| `careercrew_core/tools/capabilities.py` | 完整。服务端单一事实来源汇总（registry internal+mcp ∩ MODULE_TOOLS），`id/name/enabled/requires_hitl` 四字段，从 `settings.tools.hitl.requires_confirmation` 取 hitl 位。 |
| `careercrew_core/tools/effective.py` | 完整。`compute_effective_tools` 纯函数四层交集（client ∩ server ∩ role ∩ module），None/空 = 默认全放行，保序去重。 |
| `careercrew_api/routers/agent.py` | 完整。`GET /api/agent/capabilities?module=`，非法 module 回退全量 registry（不 404）。 |
| `careercrew_api/runtime.py` | 完整度高。`_server_allowlist` / `_hitl_requires` / `compute_effective_tools` / `_make_tools(allowed=…)` 四层接线；四类 impl（match/resume/plan/knowledge）均算 effective 并传入工厂；`begin_chat_turn(..., effective_tools=…)` 落库。 |
| `careercrew_ai/agents/langchain_agent.py` | `HitlMiddleware.wrap_tool_call` 短路不回喂，`blocked_tool_calls` 采集，`build_agent(hitl_requires=…)` 装配，`AgentResult.blocked_tool_calls` / `run_agent` 透出。 |
| 7 个 core agent 文件 + base_agent | 仅 2 行 `hitl_requires` 参数透传，干净。 |
| `careercrew_core/conversation/db.py` | `agent_runs.effective_tools JSONB` 幂等迁移（PG `DO $$ IF NOT EXISTS` + Fake 内存字段）；insert/get/list 读回。`_json_dumps` 复用已有。 |
| `careercrew_core/conversation/store.py` + `chat_lifecycle.py` | `start_run/begin_turn` 透传 `effective_tools`。 |
| `tests/api/conftest.py` | FakeRuntime 完整镜像（`tools` settings、`_hitl_requires`、`_server_allowlist`、`compute_effective_tools`、各 run_* 的 `tools`/`effective_tools` 接线）。 |
| 前端 ToolPicker / agentCapabilities 库 + 测试 | 完整，mock 桩隔离干净。 |

### 关键遗漏（本会话补齐）

1. **HITL 落库闭环缺失（严重）**：`HitlMiddleware` 采集了 `blocked_tool_calls` 且 `run_agent` 把它放到 `AgentResult.blocked_tool_calls`，但 `runtime._observability_from_result` **没有**把其翻译成 `agent_run_tool_calls` 行。brief §16.4 明确要求「agent_run_tool_calls 行写 status=awaiting_confirmation + hitl_status=pending」，死者未做到——HITL 拦截只记在内存，落库不可诊断。
2. **对应测试缺失**：无任何测试断言 blocked call → awaiting_confirmation 行。

### 修复（TDD）

- `careercrew_api/runtime.py::_observability_from_result`：新增把 `blocked_tool_calls` 翻译成 `status="awaiting_confirmation" / hitl_status="pending" / requires_hitl=True` 的 tool_call 行（与既有 completed/failed 行同表）。
- `tests/unit/test_hitl_middleware.py`：新增 `test_observability_maps_blocked_to_awaiting_confirmation`，先写断言后实现。
- 落库通路本就存在：`chat_lifecycle.finish_turn` 已把 `requires_hitl`/`hitl_status` 透传给 `store.add_tool_call`（T1.4 已建列）。

## 二、TDD 证据

| 套件 | 结果 |
|---|---|
| 后端 T3.5（test_effective_tools + test_hitl_middleware + test_agent_capabilities_api） | 18 passed（含本次新增 1 个 blocked→awaiting 测试） |
| 后端全量（disposable PG `careercrew_test`） | **758 passed, 0 failed**（exit 0；基线 739 + 19 新测试） |
| 前端 T3.5（agentCapabilities + ToolPicker） | 11 passed |
| 前端全量 vitest | 133 passed（基线 122 + 11） |
| 前端 lint | 0 errors（2 个既有 fast-refresh warning） |
| 前端 `tsc -b` | 0 errors |
| 前端 `npm run build` | ✓ built in 1.33s |

effective 纯函数矩阵覆盖：client 超集裁剪、role/module 各自裁剪、四层全交集、空=全放行、保序去重、allowlist None=不约束。capabilities：形状、module 过滤、requires_hitl 置位。HITL：中间件短路不执行 + ToolMessage 回喂 + blocked 采集 +（新增）落库行 awaiting_confirmation。API：client 越界 id 被裁且 effective_tools 记录、未传 tools=全放行、Fake+PG effective_tools JSONB 往返（PG 见 `test_conversation_pg.py::test_effective_tools_roundtrip`）。

## 三、HITL MVP 边界（无 approve/reject）

- 有副作用工具（`settings.tools.hitl.requires_confirmation`）在 `wrap_tool_call` **绝不执行**，回喂 `ToolMessage("工具 X 需要用户确认，本轮未执行（HITL）")`。
- 记录为 `agent_run_tool_calls` 行 `status=awaiting_confirmation + hitl_status=pending`（可诊断）。
- **交互式 approve/reject 恢复执行不在本任务**：需流中暂停协议（LangGraph interrupt 接入聊天流），属后续阶段；代码注释已注明。
- 默认（未选工具/未配置 hitl）行为不变。

## 四、中间件注入点

`build_agent(..., hitl_requires=…)` 在 Observability 之前插入 `HitlMiddleware`（先短路，保证被拦截调用也被观测层计时/记录）；`BaseAgent.__init__` → `build_agent` → `run_agent` → `AgentResult.blocked_tool_calls` → `runtime._observability_from_result` → `finish_turn` → `store.add_tool_call`。per-run hitl 配置由 `runtime._hitl_requires()` 从 settings 读取后经各 agent 工厂 `hitl_requires=` 传入。

## 五、并行共存 / 暂存日志

### 分批提交

1. `feat(agent): capabilities endpoint effective tool intersection and hitl guard` — 25 文件（后端 + 测试）。
2. `feat(web): tool picker with capability-driven options` — 5 文件（前端）。

### 混合文件的手术分离（`git apply --cached --recount` 行级暂存）

| 文件 | T3.5 暂存 hunk | foreign 保留 hunk |
|---|---|---|
| `schemas.py` | MatchRequest/ResumeRequest/KnowledgeAskRequest 的 `tools` | `display_name`、`UpdateDisplayNameRequest` |
| `main.py` | `import ... agent` + `include_router(agent.router)` | 异常处理器（`_has_cjk`/`_validation_detail`/503/422/500 handler） |
| `routers/chat.py` | 3× `tools=req.tools` | `friendly_error` import + `failed` 标志 + 错误分支重构 |
| `tests/api/test_sse_streams.py` | `slow_match(..., **kwargs)` | `回答生成超时` 中文化断言 |
| `tests/api/test_stable_ids.py` | `boom(..., **kwargs)`（整文件单 hunk） | （无 foreign） |
| `tests/integration/test_conversation_pg.py` | `test_effective_tools_roundtrip`（文件尾追加 hunk） | （无 foreign） |

### foreign 完全保留（提交后 `git status` 复核）

`auth/*`、`routers/{auth,consult,data,interview,knowledge,resume,sse}.py`、`main.py`/`chat.py`/`schemas.py`/`test_sse_streams.py` 的 foreign 残段、前端 `DisplayNameEditor/RoleBadge/ToastHost/UserManagementPanel/ConversationHeader/lib/{errors,toastBus}/data/login-locked.png` 及众多页面 foreign 修改、其余 foreign test（auth/sse_bridge/sse_streams/quality_reviewer）**均保持未暂存状态**，未被 revert/stage。

### 关于 `**kwargs` 判定说明

`test_sse_streams.py` 与 `test_stable_ids.py` 的 `**kwargs` 变更被归入 T3.5 提交：它们是 T3.5 给 `run_match_stream` 新增 `tools=` 参数后，测试内 `run_match_stream` 覆盖函数必须容忍新 kwarg 的直接结果；若随 foreign 提交，HEAD 上 T3.5 的 `tools=req.tools` 会使这两处覆盖抛 TypeError。已在报告记录此判定。

## 六、文件清单

**后端/核心（提交 1）**：`careercrew_api/routers/agent.py`（新）、`careercrew_core/tools/{capabilities,effective}.py`（新）、`careercrew_ai/agents/langchain_agent.py`、`careercrew_core/agents/{base_agent,career_planner,interviewer,job_matcher,knowledge_advisor,resume_advisor,salary_negotiator}.py`、`careercrew_api/{chat_lifecycle,runtime,main}.py`、`careercrew_api/routers/chat.py`、`careercrew_api/schemas.py`、`careercrew_core/conversation/{db,store}.py`、`tests/api/{conftest,test_agent_capabilities_api,test_sse_streams,test_stable_ids}.py`、`tests/unit/{test_effective_tools,test_hitl_middleware}.py`、`tests/integration/test_conversation_pg.py`。

**前端（提交 2）**：`careercrew_web/src/components/prompt/{ToolPicker,ToolPicker.test}.tsx`（新）、`careercrew_web/src/lib/{agentCapabilities,agentCapabilities.test}.ts`（新）、`careercrew_web/src/components/prompt/PromptComposer.tsx`（`tools` 插槽）。

## 七、自审发现

- capabilities 端点对非法 module 回退全量 registry（不 404）；`enabled` 恒 `True`（仅结构性预留禁用位）——已在 `capabilities.py` docstring 说明。
- `effective_tools` 的 role_allowlist 未从 settings 读取（settings 无 role→tools 映射结构），已按 brief「至少结构上分层」：纯函数留 role/module 参数，runtime 用 module 层，role 层留待后续配置。已在注释说明。
- `_observability_from_result` 新增分支对 `blocked_tool_calls` 缺失/None 静默降级（兼容旧 `AgentResult`）。
- 前端页面 send 逻辑仍在 defer（brief 允许）；ToolPicker/PromptComposer 插槽/lib 已交付，页面接线因并行冲突留待后续。

## 八、疑虑

1. `enabled` 恒 True、role_allowlist 未落配置——若后续要求真实禁用位/角色级裁剪，需补 settings 结构 + capabilities/effective 联动。
2. `MODULE_TOOLS` 与 `_make_tools(kind)` 的 per-kind 构造是两套映射（前者「可见性声明」、后者「实际构造」），future 需单源化，避免两处漂移（已在代码注释提示）。
3. HITL 恢复执行（approve/reject）仍缺失，属已声明的后续阶段。

## Fix Round (review findings)

评审结论「Needs fixes」：1 Critical + 2 Important + 1 Minor，本会话全部修复（提交 `e8f1e33`）。

### 修复内容

1. **Critical 1 — 默认路径静默禁用真实工具**：`settings.yaml` `tools.registry.internal` 补登 `search_jobs` / `salary_query` / `read_image`（与 `_make_tools` 的 matcher / planner+salary / knowledge 分支对齐），使默认（未传 `tools`）路径不再把它们从 bound 集合裁剪掉。
2. **Important 3 — recorded effective_tools 多报**：选「align MODULE_TOOLS 1:1 with `_make_tools` 分支」这条更小改动——`capabilities.py::MODULE_TOOLS` 逐 module 对齐 `_make_tools` 实际构造集（`chat`=planner 不再声明未构造的 `memory_write`/`read_image`；其余 module 顺序对齐）。`_server_allowlist`（registry ∩ MODULE_TOOLS）因此严格等于真正 bound 集。
3. **Important 2 — interview + consult 未接线**：`runtime.new_consult_agent` 增 `allowed`/`hitl_requires` 并透传给各顾问工厂（含 `SalaryNegotiator.hitl_requires`）；`schemas.py::QuestionRequest/InterviewChatRequest/ConsultRequest` 增 `tools`；`routers/interview.py` 与 `routers/consult.py` 计算 `effective`/`hitl` 并传入 agent 工厂、`_begin_chat_turn(effective_tools=…)`；`consult_orchestrator` 的 `_build_agent_node` 把 `blocked_tool_calls` 随 `consult_calls` 透出，consult 路由经 `_observability_from_result` 汇总后落 `awaiting_confirmation` 行。
4. **Minor 5 — 死 `_KNOWN_MODULES`**：`routers/agent.py` 删除未使用的 `_KNOWN_MODULES`。

### 测试命令 + 结果

- 定向：`uv run pytest tests/unit/test_effective_tools.py tests/unit/test_hitl_middleware.py tests/api/test_agent_capabilities_api.py tests/api/test_interview_api.py tests/api/test_consult_api.py -q` → **38 passed**（新增 6 项：MODULE_TOOLS 1:1 对齐、capabilities 暴露 search_jobs/salary_query/read_image、match 默认含 search_jobs、interview/consult 越界裁剪、consult HITL awaiting_confirmation）。
- 全量（disposable DB）：`$env:POSTGRES_TEST_DSN = .../careercrew_test; uv run pytest -q` → **764 passed, 0 failed**（基线 758 + 6 净新增）。

### 提交

- `e8f1e33 fix(agent): reconcile default allowlist with bound tools and wire interview consult`（13 文件，+220/-24）。

### 暂存处置

仅暂存本会话文件；`schemas.py`、`routers/consult.py`、`routers/interview.py` 为混合文件，采用 hunk 级暂存（`git add -p`）：schemas.py（5 hunks 暂 3）、consult.py（5 hunks 暂 3）、interview.py（10 hunks 暂 5）。foreign hunks（`friendly_error`/超时中文化、`failed` 标志、`display_name`/`UpdateDisplayNameRequest`）保持未暂存，提交后 `git status` 复核仍为 ` M` 未动。

## Final review fix round

### 修复内容

1. **Critical — 生产 HITL 闭环可达**：`submit_application` 现由 `CareerCrewRuntime._make_tools("matcher")` 实际绑定，登记在 `settings.tools.registry.internal` 和 `MODULE_TOOLS["matcher"]`，并是唯一仍配置为 `requires_confirmation` 的 MVP 动作。没有 approve/reject 恢复协议时，`HitlMiddleware` 一律短路，因此不会执行该 mock 动作。
2. **Important — consult recorded set 精确**：新增 `MODULE_TOOLS["consult"]`，其值是 salary/planner/matcher/resume/interviewer 实际构造工具的精确并集；`read_image`、MCP 和任何仅注册但没有会诊顾问可构造的工具不再写入 `effective_tools`。
3. **回归覆盖**：生产 `CareerCrewRuntime` 测试验证实际绑定 → `build_agent/run_agent` → `awaiting_confirmation/pending/requires_hitl` tool-call 落库；consult API 覆盖默认并集与显式请求子集两条持久化路径。

### 变更文件

`config/settings.yaml`；`careercrew_api/runtime.py`；`careercrew_core/tools/capabilities.py`；`tests/api/conftest.py`；`tests/api/test_consult_api.py`；`tests/unit/test_effective_tools.py`；`tests/unit/test_hitl_middleware.py`。

### 命令与结果

- `$env:PYTHONPATH=(Get-Location).Path; F:\Python_develop\miniconda3\envs\careercrew\python.exe -m pytest tests/unit/test_hitl_middleware.py tests/unit/test_effective_tools.py -q -ra` → **17 passed**。
- `$env:PYTHONPATH=(Get-Location).Path; F:\Python_develop\miniconda3\envs\careercrew\python.exe -m pytest tests/api/test_consult_api.py::test_consult_tools_outside_allowlist_clipped tests/api/test_consult_api.py::test_consult_default_effective_tools_are_exact_advisor_union -q -ra` → **2 passed**。
- `$env:PYTHONPATH=(Get-Location).Path; F:\Python_develop\miniconda3\envs\careercrew\python.exe -m pytest tests/unit/test_hitl_middleware.py tests/unit/test_effective_tools.py tests/api/test_consult_api.py tests/api/test_agent_capabilities_api.py -q -ra` → **33 passed**。

### 提交

- `204b67c892de8f0da800e093ab339f93f861f91d fix(agent): bind production hitl tool and constrain consult tools`
