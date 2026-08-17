# Task T1.6 报告 — Regenerate 后端（Phase 1 收尾）

## 状态：DONE

## 1. 审计结论（前任实现者遗留改动）

前任实现者的未提交改动质量较高，绝大部分与 brief 契约一致，可直接保留。逐文件审计：

**正确（保留）：**

- `careercrew_core/conversation/db.py`：`regeneration_keys` 表（`user_id VARCHAR(64)` / `key VARCHAR(200)` / `message_id` / `created_at`，`UNIQUE(user_id, key)`）用 `CREATE TABLE IF NOT EXISTS` 幂等落地；`insert_message` 已带 `metadata JSONB` 往返；`get_regeneration` / `create_regeneration` 已实现。
- `careercrew_core/conversation/store.py`：`add_user_message(..., metadata=None)`；`get_regeneration` / `create_regeneration` 透传；`get_run` 已有（版本串复用依赖）。
- `careercrew_api/chat_lifecycle.py`：`begin_regeneration()` 正确复用 turn（不新建 turn / 用户消息），新建 assistant message（`regenerated_from_message_id=旧 id`）+ 新 run。
- `careercrew_api/runtime.py`：`run_regenerate_stream` / `validate_regenerate` / `_is_latest_assistant_version` / `_dispatch_regenerate` 结构清晰，按模块分派 matcher/resume/chat/knowledge，consult/interview → 409，版本串从旧 run 行复用，`_observability_from_result` 与 retrieval 写入复用首次路径。
- `careercrew_api/routers/threads.py`：`POST /api/messages/{message_id}/regenerate` 支持 `Idempotency-Key` 头，同步 404/409 映射，成功 NDJSON 流（stage → chunk → done 带稳定 ID）。
- 4 个测试文件（`tests/{unit,integration,api}/test_regenerate_*.py`）已写且覆盖面完整（校验矩阵、幂等、API turn 不变性、PG 迁移）。**（备注：任务简报称“无测试”，实际已有完整测试，属简报过期。）**

**发现并修复的偏差（前任做错/做漏）：**

1. **PG 与 Fake 幂等语义不一致**：`FakeConversationDb.create_regeneration` 冲突返回 `None`，而 `PostgresConversationDb.create_regeneration` 冲突返回既有 `message_id`，导致 PG 集成测试 `test_regeneration_keys_idempotent_migration` 断言失败。已统一为“冲突返回 None”（与 store 契约 docstring 一致），路由侧复用 `get_regeneration`。
2. **用户消息 metadata 写侧缺失**：`_dispatch_regenerate` 读 `meta.get("jd_text")` / `meta.get("category")` / `meta.get("scope")`，但首次运行路径 `_begin_chat_turn` → `begin_turn` → `add_user_message` 从未写入这些 metadata —— resume regenerate 会退化到截断摘要、knowledge 会退化到空 category / `all` scope，无法“忠实重跑”。已补：`begin_turn` 与 `_begin_chat_turn` 增加 `user_metadata` 可选参数；`_run_resume_stream_impl` 写 `{"jd_text": jd_text[:5000]}`，`_run_knowledge_ask_stream_impl` 写 `{"category":…, "scope":…}`。
3. **跨特性耦合**：`threads.py` import 了属于并行会话（错误文案中文化重构）的 `friendly_error`（sse.py 未提交项）。若独立提交 threads.py 将依赖未提交的 `friendly_error` 而无法运行。已改为 threads.py 内联 `error_event(f"生成失败：{e}")`，移除外来 import，使 T1.6 提交自足、可独立 import/运行。

**外来（display_name + 错误文案重构）改动判定，未触碰：**

- `careercrew_api/auth/*`、`routers/auth.py`、`schemas.py`（`PublicUser.display_name` + `UpdateDisplayNameRequest`）、前端 `careercrew_web/**`、`data/login-locked.png` → display_name 特性。
- `main.py`（RuntimeInitError→503 / RequestValidationError→422 中文）、`routers/{chat,consult,data,interview,knowledge,resume}.py`、`sse.py`（`friendly_error` + `failed` 标记 + 中文超时文案）、`tests/{test_auth_api,test_sse_bridge,test_sse_streams,test_quality_reviewer_dependency}` → 错误文案中文化重构。
- `schemas.py` 经查无 T1.6 内容（regenerate 路由直接用 `Header`，无新增 schema），与简报“mixed”描述不符，实际为纯外来。

## 2. 完成的实现（full scope）

- Store：`add_user_message` metadata（db + Fake + PG 集成各一处）+ `regeneration_keys` 表幂等迁移 + `get/create_regeneration`。
- Runtime：`run_regenerate_stream` + 六模块按需分派（matcher/resume/chat/knowledge 实跑；consult/interview → 409）+ resume `jd_text` / knowledge `category`/`scope` 从用户消息 metadata 恢复重跑。
- 路由：`POST /api/messages/{message_id}/regenerate`（幂等头 / 404 / 409 JSON 映射 / NDJSON 流 done 携带 §9 字段 + `regenerated_from_message_id`）。
- 生命周期：`begin_regeneration` 复用 turn；新 message（`regenerated_from_message_id`）+ 新 run（版本串复用旧 run）。
- 写侧补全（本次修复）：首次 resume/knowledge 用户消息写入重跑所需 metadata。

## 3. TDD 证据

- 新增/现有 T1.6 测试 24 项（`test_regenerate_store` 6 / `test_regenerate_runtime` 11 / `test_regenerate_api` 6 / `test_regenerate_pg` 3 中 DSN 命中即跑）。
- 本次新增：`test_begin_turn_writes_user_metadata`（写侧回归，先写后改绿）。
- 聚焦测试全绿：
  - `tests/unit/test_regenerate_store.py tests/unit/test_regenerate_runtime.py` → 17 passed。
  - `tests/api/test_regenerate_api.py` → 6 passed。
  - `tests/integration/test_regenerate_pg.py` → 3 passed（修复幂等语义后）。
- 全量：`$env:POSTGRES_TEST_DSN=…/careercrew_test; uv run pytest -q` → **606 passed**（基线 579，含并行会话 + 本任务 24 项）。绿。

## 4. 暂存 / 提交日志

分两个提交，仅暂存 T1.6 文件（`git add <file>` 逐文件，未用 `git add -A` / `git add -p`）：

- `0a28ef6 feat(conversation): user message metadata and regeneration idempotency`
  - `careercrew_core/conversation/db.py`、`careercrew_core/conversation/store.py`、`tests/unit/test_regenerate_store.py`、`tests/integration/test_regenerate_pg.py`
- `b0ed935 feat(chat): regenerate endpoint with stable turn run message ids`
  - `careercrew_api/chat_lifecycle.py`、`careercrew_api/runtime.py`、`careercrew_api/routers/threads.py`、`tests/api/conftest.py`、`tests/api/test_regenerate_api.py`、`tests/unit/test_regenerate_runtime.py`

**保留的外来 hunk（未暂存、未还原，提交后仍在工作树）：** `careercrew_api/auth/*`、`routers/auth.py`、`schemas.py`、`main.py`、`routers/{chat,consult,data,interview,knowledge,resume}.py`、`sse.py`、`careercrew_web/**`、`data/login-locked.png`、`.superpowers/sdd/progress.md`、`tests/{test_auth_api,test_sse_bridge,test_sse_streams,test_quality_reviewer_dependency}.py`。经提交前后 `git status --short` 复核，外来 hunk 完整存活，无丢失。

## 5. 文件清单（改动）

- `careercrew_core/conversation/db.py`（regeneration_keys 表 + metadata + 幂等语义统一）
- `careercrew_core/conversation/store.py`（add_user_message metadata + get/create_regeneration）
- `careercrew_api/chat_lifecycle.py`（begin_regeneration + begin_turn user_metadata）
- `careercrew_api/runtime.py`（RegenerateConflictError + regenerate 分派 + 写侧 metadata）
- `careercrew_api/routers/threads.py`（regenerate 路由，移除外来 friendly_error 依赖）
- `tests/{unit,integration,api}/test_regenerate_*.py`（新增）
- `tests/api/conftest.py`（FakeRuntime regenerate 桩）

## 6. 自审发现

- 旧消息不可变：`_finish_chat_turn` 只写新 assistant message，旧 message 从不 mutate（`test_regenerate_stable_turn_new_run_message` 断言 `old["content"] == "answer"`）。
- 版本链：`regenerated_from_message_id` 链完整，`list_message_versions` 回溯正确（root→leaf）。
- 最后一条限制：`_is_latest_assistant_version` 判定“有后继指向它即为中间版本”，中间版本 → 409；最新版才可 regenerate。
- 幂等：同 key 二次返回首次 message（`test_regenerate_idempotency_key`），无 key 每次新 run。
- 跨用户：`get_message` 按 user_id 隔离，跨用户 → 404（`test_regenerate_cross_user_404`）。
- consult/interview → 409（`test_regenerate_consult_409` / `test_regenerate_interview_409`）。
- 外来 hunk 完整性：提交后 `git status --short` 确认全部 display_name / 错误文案改动仍在未暂存工作树。

## 7. 疑虑 / 备注

- **幂等持久化时序**：`Idempotency-Key` 的 `create_regeneration` 在 done 事件之后才登记（`gen_with_idem`），若流在中途被客户端断开但已产出新 run，该 key 不会登记，后续同 key 会重跑。这是避免“流失败误占 key”的取舍，路由已注释；与 brief 的“避免双击生成两次”在正常完整流场景满足。
- **resume 模块语义**：`run_resume_stream` 的 `jd_text` 截断至 5000 字符存 metadata（brief 约定）；`routers/resume.py` 的对话式 `/chat` 端点直接 `new_resume_advisor`（不经过 `run_resume_stream`），其用户消息不带 `jd_text` metadata —— 该路径产生的 assistant 消息 regenerate 时 `jd_text` 会退化到 `question` 内容。属既有架构（brief §B.4 仅要求 `run_resume_stream` 路径），已按 brief 范围处理，未越界改动。
- **跨特性耦合已消除**：`threads.py` 不再依赖未提交的 `sse.friendly_error`；待并行会话提交 sse.py 后无冲突（两特性在 sse.py 内是不同函数，后续合并无交集）。

报告文件：`F:\agent_develop\CareerCrew\.superpowers\sdd\reports\t16-report.md`

## Fix Round (review findings)

复审裁决 "Needs fixes"，本修复轮针对四项 findings：

1. **线程末条消息校验缺失**（`runtime.py`）：`validate_regenerate` 仅有版本链最新判定，未阻止"后续 turn 的 assistant 消息存在时，重跑早期 turn 最新版"。新增 `_is_last_assistant_in_thread`（以 turn 的 `sequence_no` 为主序、消息 `created_at` 为次序，遍历线程内其他 assistant 消息，任一更晚即拒绝 409），并与既有版本链判定并列为独立条件。补充 `ConversationStore.get_turn` 透传（读 sequence_no）。
2. **幂等键预留过晚**（`threads.py`/`db.py`/`store.py`）：原逻辑在 done 事件后才 `create_regeneration`，并发同 key 双跑。改为上游原子预留：新增 `reserve_regeneration`（`INSERT ... ON CONFLICT DO NOTHING`，冲突返回既有 `message_id`，成功返回 None）/ `complete_regeneration`（完成后回填）/ `release_regeneration`（失败释放，不污名化 key）。`regeneration_keys.message_id` 改为可空（幂等 `DROP NOT NULL` 迁移），预留时 NULL、完成后回填。路由侧：命中既有 id → replay（不重跑）；本次成功预留 → 完成后回填、失败释放。无 key 不预留（幂等行为不变）。
3. **metadata 保真降级**（`runtime.py`）：resume regenerate 缺 `jd_text` metadata（conversational /chat 路径、legacy 行）→ 409（明确 detail：无法忠实重建输入，请重新发起简历定制）；knowledge regenerate 缺 category/scope → 保留端点默认回退（`""`/`"all"`，等价忠实重跑）并 `logging.warning`。
4. **replay done 事件缺 §9 版本字段**（折入 fix 2 的 replay 路径）：`_replay_done_event` 从 run 行读 `model`/`prompt_version`/`agent_version`，并补 `status`、`regenerated_from_message_id`，与正常路径字段集一致。`FakeRuntime`（tests/api/conftest.py）同步补线程末条校验。

**改动文件**：`careercrew_api/runtime.py`、`careercrew_api/routers/threads.py`、`careercrew_core/conversation/db.py`、`careercrew_core/conversation/store.py`、`tests/api/conftest.py`、`tests/unit/test_regenerate_runtime.py`、`tests/unit/test_regenerate_store.py`、`tests/api/test_regenerate_api.py`、`tests/integration/test_regenerate_pg.py`。

**测试命令与结果**：

```
uv run pytest tests/unit/test_regenerate_runtime.py tests/unit/test_regenerate_store.py tests/api/test_regenerate_api.py tests/integration/test_regenerate_pg.py -q
# → 36 passed

$env:POSTGRES_TEST_DSN = "postgresql://careercrew:careercrew@localhost:5432/careercrew_test"
uv run pytest tests/integration/test_regenerate_pg.py -q
# → 4 passed

$env:POSTGRES_TEST_DSN = "postgresql://careercrew:careercrew@localhost:5432/careercrew_test"
uv run pytest -q
# → 615 passed, 3 warnings（基线 606，新增 9 项全绿）
```

**提交**：`47ef2e7` `fix(chat): thread-last regenerate guard, upfront idempotency reservation, fidelity 409`（9 文件，逐文件 `git add`，未用 `git add -A`；外来 display_name / 错误文案改动完整保留，未触碰）。

## Fix Round 2 (idempotency tri-state)

复审 finding：`reserve_regeneration` 返回 `None` 同时表达"fresh 预留"与"已存在但 message_id 仍为 NULL（首个请求进行中）"两种含义，路由因此把"进行中"误判为"fresh"，对并发同 key 请求重新 dispatch —— 恰是上游预留要消除的双跑。

**修复（三态契约）：**

- `careercrew_core/conversation/db.py` + `store.py` + `FakeConversationDb`：`reserve_regeneration(user_id, key, message_id=None)` 改为返回 `(state, message_id)` 元组：
  - `("reserved", None)` — 本次 `INSERT ... ON CONFLICT DO NOTHING` 成功（fresh 插入），应 dispatch。
  - `("exists", <message_id>)` — 行已存在且 message_id 已回填（已完成），应 replay。
  - `("exists", None)` — 行已存在但 message_id 仍为 NULL（首个请求进行中），应 409。
  保留原子 `INSERT ... ON CONFLICT DO NOTHING` + 读回；`message_id` 参数使预留路径与 create 语义对齐（Fake 存 None、PG 写 NULL）。
- `careercrew_api/routers/threads.py`：`("reserved", _)` → 继续 dispatch；`("exists", message_id)` → replay 该 message（既有行为）；`("exists", None)` → `HTTPException(409, detail="该幂等键的重新生成正在处理中")`，不 dispatch。

**测试：**

- 更新 in-progress-window 断言（原先 `reserve(...) is None`）：`test_regenerate_store.py`、`test_regenerate_pg.py` 改用三态元组断言（`("reserved", None)` / `("exists", None)` / `("exists", "m1")`）。
- 新增 API 级测试 `test_regenerate_idempotency_in_progress_409`：同 key 首个请求进行中（message_id 未回填）时并发同 key 请求返回 409，且不产生第二条 assistant message；release 后同 key 可重新 dispatch。
- 顺序 replay 测试（`test_regenerate_idempotency_key` / `test_regenerate_idempotency_replay_done_fields`）保持绿色。

**测试命令与结果：**

```
uv run pytest tests/unit/test_regenerate_store.py tests/unit/test_regenerate_runtime.py tests/api/test_regenerate_api.py tests/integration/test_regenerate_pg.py -q
# → 34 passed, 4 skipped（PG 集成无 DSN 时跳过）

$env:POSTGRES_TEST_DSN = uv run python -c "import re;raw=open('.env',encoding='utf-8').read();print(re.search(r'^DATABASE_URL=(.+)$',raw,re.M).group(1).strip().rsplit('/',1)[0]+'/careercrew_test')"
uv run pytest -q
# → 617 passed, 3 warnings（基线 615，新增 1 项 API 测试全绿）
```

**提交**：`69ed84d` `fix(chat): tri-state idempotency reservation blocks concurrent duplicate regeneration`（6 文件，逐文件 `git add`，未用 `git add -A`；外来改动未触碰）。
