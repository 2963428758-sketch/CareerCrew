# Task T1.2 报告 — 对话流接入稳定 ID + done 事件 + threads/messages API

## 状态：DONE_WITH_CONCERNS

## 实现内容

### 1. 存储层扩展（`careercrew_core/conversation/`）
- `ConversationStore.set_message_content(user_id, message_id, content, status="completed")`：流式结束回写 assistant message 最终内容 + 状态 + completed_at（带所有权校验，风格对齐 T1.1）。
- `ConversationStore.set_message_run_id(user_id, message_id, run_id)`：message 先于 run 创建，run 生成后回填 message.run_id（满足 §37 messages API 需要每条 assistant message 带 run_id）。
- 对应在 `ConversationDb`/`PostgresConversationDb`/`FakeConversationDb` 三个层面补齐 `update_message_content` / `update_message_run_id` 契约与实现，抽 `_read_message` 复用读路径。

### 2. 生命周期辅助（新模块 `careercrew_api/chat_lifecycle.py`）
- `TurnContext` dataclass（thread_id/legacy_thread_id/turn_id/user_message_id/assistant_message_id/run_id/module/agent_id/model/prompt_version/agent_version/started_at/user_id）+ `latency_ms()` + `done_fields(status)` 组装 §9 字段。
- `begin_turn(...)`：ensure_conversation → next_turn → add_user_message(completed) → add_assistant_message(空内容) → set_message_status(streaming) → start_run → set_message_run_id → finish_run(status=streaming)。
- `finish_turn` / `fail_turn`（记录 error_type/error_summary）/ `cancel_turn`（latency 计算 + finished_at）。
- `StreamResult` dataclass（content/sources/turn）供 knowledge 等返回结构化字段的流使用。

### 3. Runtime 接线（`careercrew_api/runtime.py`）
- `_ensure_heavy()` 初始化 `self.conversation_store = ConversationStore(create_conversation_db(settings))`（进程级单例，Postgres/Fake 自动选择）。
- 新增 `_conversation_model()`（settings.llm.model）+ `_begin_chat_turn` / `_finish_chat_turn` / `_fail_chat_turn` / `_cancel_chat_turn` 包装（失败不阻断主流程，日志告警）。
- 四个 run 流（match/resume/plan/knowledge）接入生命周期、异常路径 mark failed 后 re-raise、返回 `StreamResult`；episodic 双写（record_user_message / record_thread_messages）**保留不动**。
- module/agent_id 取值（对齐 brief §A.3）：
  - match→matcher/job_matcher；resume→resume/resume_advisor；plan→chat/career_planner；knowledge→knowledge/knowledge_advisor；consult→consult/consult_orchestrator；interview→interview/interviewer。

### 4. 路由适配（done 事件 §9 字段）
- `careercrew_api/sse.py` 新增 `turn_done_fields(turn)` 把 TurnContext 转成 done 附加字段（None 退化兼容）。
- `chat.py`（match/resume/plan）、`knowledge.py`（ask）、`interview.py`（questions + chat）、`consult.py` 的 done 事件携带 §9 全部字段（thread_id/turn_id/message_id/run_id/model/prompt_version/agent_version/status + 可选 legacy_thread_id + 保留 content）；interview/consult 因是 router 内联跑 agent，直接在 router 层 begin/finish turn。
- interview 的 `chat`/`questions`、consult 的 `_worker_impl` 均接入 begin/fail/finish/cancel。

### 5. threads 路由（新模块 `careercrew_api/routers/threads.py`）
- `POST /api/threads`：body {module, title?, retrieval_scope?, thread_id?} → ensure_conversation（缺省 thread_id 服务端生成 UUID；显式提供按 legacy 映射），同时 `register_thread`（memory 线程元数据，sidebar 兼容），返回 {thread_id, module, title, created_at}。module 校验 422。
- `GET /api/threads/{thread_id}/messages`：返回 [{id, turn_id, role, content, status, run_id, regenerated_from_message_id, created_at, completed_at}]，按 turn sequence_no + created_at 排序；支持 UUID 或 legacy id；所有权不匹配 404。
- `main.py` 注册（threads 在 data 之前，POST 归 conversation；data.py 保留 GET/PATCH/DELETE memory 线程）。

## TDD 证据

- **RED**：先写 `tests/unit/test_chat_lifecycle.py`（6 用例）与 `tests/api/test_stable_ids.py`（13 用例），最初因 `set_message_content`/`set_message_run_id` 缺失、`TurnContext` 未定义而无法导入/失败。
- **GREEN**：实现后 `uv run pytest tests/unit/test_chat_lifecycle.py tests/api/test_stable_ids.py` → **19 passed**。
- 全量 `uv run pytest` → **519 passed, 12 skipped**（基线 513；+20 新测试后 net +6……详见疑虑）。

## 文件改动

新增：
- `careercrew_api/chat_lifecycle.py`
- `careercrew_api/routers/threads.py`
- `tests/unit/test_chat_lifecycle.py`
- `tests/api/test_stable_ids.py`

修改：
- `careercrew_core/conversation/store.py` / `db.py`
- `careercrew_api/runtime.py` / `sse.py` / `main.py`
- `careercrew_api/routers/chat.py` / `knowledge.py` / `consult.py` / `interview.py` / `data.py`
- `tests/api/conftest.py`

## 提交

- `8f60df4` feat(conversation): add set_message_content/run_id + chat lifecycle helper
- `bcecb1a` feat(chat): wire stable IDs into 6 flows + threads/messages API
- `b96f794` test(chat): stable-ID done events + threads/messages API coverage
- `8778dd1` refactor(chat): tidy StreamResult annotations and drop dead code

## 自审发现

- ✅ 六流全覆盖（match/resume/plan/knowledge.ask/consult/interview questions+chat）。
- ✅ 异常 path 标 failed、StreamCancelled 标 cancelled（consult）；latency 由 TurnContext.started_at 计算。
- ✅ episodic 双写保留；conversation 表为新增 Source of Truth。
- ✅ 所有权：messages 端点他人 → 404（OwnershipError → HTTPException）。
- ✅ TEST 卫生：FakeRuntime 内建 FakeConversationDb + 真实 begin/finish turn，测试走真实依赖链。
- ✅ YAGNI：删除 threads.py 里未用的 `_is_uuid`/`ResourceNotFoundError` 导入；wrapper 返回注解统一 `StreamResult`。

## 疑虑 / Concerns

1. **POST /api/threads 路由冲突（关键）**：`data.py` 原已有 memory 后端的 `POST /api/threads`（body 含必填 thread_id）。brief §B 要求新 `threads.py` 也挂 `POST /api/threads`（服务端生成 UUID）。二者无法共存。我采用「统一 handler」方案：把 `data.py` 的 POST 迁入新 `threads.py`（新 body 可选 thread_id，兼容旧形参），data.py 保留 GET/PATCH/DELETE memory 线程。**此决策未经人工确认**（子代理无法交互提问），若 plan 作者本意是「对话 create 走独立路径」或「data.py 的 memory 登记另有归属」，需在后续任务修正。
2. **resume 的 module 取值**：brief §A.3 列出 module 含 `resume`，但既有 episodic 对 resume 用 `matcher`。conversation 表里我按 brief 取值 `resume`（episodic 保持 `matcher` 不动），两者现在不一致——若质量系统后续按 module 对齐 episodic 会有偏差。
3. **未跑 Postgres 集成**：全量测试用了 FakeConversationDb；`tests/integration/test_conversation_pg.py` 需 POSTGRES_TEST_DSN 真库，本环境未跑（属 T1.1 已交付、T1.2 未改其 DDL 之外的路径）。`update_message_content/run_id` 的新 SQL 未在真库验证。
4. **并行任务污染**：work tree 里存在另一并行的 auth「display_name」未提交改动（`careercrew_api/auth/*`、`tests/fakes.py`、前端若干），导致全量测试中 `test_auth_api.py::test_password_login...` 偶发失败（隔离跑通过，为顺序依赖的 flaky）。**非本任务引入**，但全量 `519 passed + 1 failed` 的这一失败来自该并行改动，请一并留意。

## 建议后续

- 确认「POST /api/threads 统一 handler」与 plan 意图一致；若否，改独立路径并在 T1.6 regenerate 前定案。
- T1.5 替换 prompt_version/agent_version 为真值、T1.4 补 tokens 时，lifecycle 的 `begin_turn` 已预留 model/prompt_version/agent_version 参数。

## Fix Round (PG coverage)

### 变更
- 扩展 `tests/integration/test_conversation_pg.py`，新增 4 个用例（原 4 个 → 8 个），针对 T1.2 新增 SQL 在真实 Postgres 上的行为：
  - `test_set_message_content_roundtrip`：`set_message_content` 流式结束后内容/状态/`completed_at` 回写与真库回读，含显式 `status` 参数与所有权拒绝。
  - `test_set_message_run_id_roundtrip`：`set_message_run_id` 回填 `message.run_id` 并持久化（含回填前 NULL 断言、跨用户拒绝）。
  - `test_run_lifecycle`：`start_run`（pending / finished_at NULL）→ `finish_run` 写 status/tokens/latency/langsmith_run_id/finished_at 并回读。
  - `test_run_failure_persisted`：`finish_run` 失败路径 error_type/code/summary + finished_at 落库 + 所有权拒绝。
  - 抽取 `_begin_chat_turn` 复现 T1.2 `begin_turn` 顺序（空内容 assistant → set_message_status(streaming) → start_run → set_message_run_id）。

### 测试命令 + 结果
- `uv run pytest tests/integration/test_conversation_pg.py -q` → **8 passed**（真实 Postgres disposable 库 careercrew_test）。
- 全量（设置 POSTGRES_TEST_DSN）`uv run pytest` → **536 passed, 3 warnings**（0 failed / 0 skipped；原本需跳过 DSN 的集成用例现全部实跑，auth flaky 未复现，全绿）。

### 提交
- `2382319` test(conversation): integration coverage for message content and run lifecycle

## Fix Round (review findings)

### 变更
针对评审三条 Important 意见逐一修复（无行为变更）：
1. **resume module 不一致**（`careercrew_api/runtime.py` ≈:521）：在 conversation 记录站点加短注释，说明 `module="resume"`（canonical，对齐前端 sidebar/threadStore）与 episodic 双写遗留 `module="matcher"` 有意不一致，引导 T1.5/T1.6 勿误迁。
2. **`begin_turn` 复用 `finish_run(status="streaming")`**（`careercrew_api/chat_lifecycle.py` ≈:135）：采用方案 (a)——`ConversationStore.start_run` 新增 `status: str = "pending"` 参数并透传给 `insert_run`（Postgres/Fake 两层 `insert_run` 本就接收 status，无 DDL/SQL 改动），`begin_turn` 直接以 `status="streaming"` 插入并删除 `finish_run` 调用。`finish_run` 保持仅用于终态（completed/failed/cancelled）。
3. **`chat.py` 死 wrapper `_turn_done_fields`**：删除该一层包装，match/resume/plan 三处 done 事件直接调用已 import 的 `turn_done_fields`。

### 测试命令 + 结果
- `uv run pytest tests/unit/test_conversation_store.py tests/unit/test_chat_lifecycle.py tests/api/test_stable_ids.py -q` → **47 passed**（含新增 `test_start_run_status_param` / `test_start_run_default_pending` 覆盖 insert-as-streaming 路径）。
- `uv run pytest tests/integration/test_conversation_pg.py -q`（POSTGRES_TEST_DSN 指向 careercrew_test）→ **9 passed**（新增 `test_start_run_streaming_status` 在真实 Postgres 验证 `start_run(status="streaming")` 直接落 streaming 初始态、`finished_at` NULL、再以 `finish_run` 收尾；`_begin_chat_turn` 与 `test_run_lifecycle` 的起始态断言同步改为 streaming）。
- 全量（设置 POSTGRES_TEST_DSN）`uv run pytest -q` → **539 passed, 0 failed, 0 skipped**（基线 536 + 3 新增；exit 0，全绿，auth flaky 未复现）。

### 提交
- `21211a1` fix(chat): canonical resume module note, run status insert, drop dead wrapper
