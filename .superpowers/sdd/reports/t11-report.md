# T1.1 报告 — 对话核心存储：conversations/turns/messages/agent_runs 表 + ConversationStore

## 状态：DONE_WITH_CONCERNS

## 实现内容

新增包 `careercrew_core/conversation/`（三个业务文件 + `__init__.py`），风格镜像 `careercrew_core/memory/db.py`：

1. **`uuid7.py`** — RFC 9562 风格 UUIDv7：48bit Unix 毫秒时间戳 + 80bit 随机尾，
   version=7、variant=0b10。按 RFC 9562 method B 语义进程内单调（同一毫秒内随机尾 +1），
   线程安全（`threading.Lock` 保护单调计数）。满足「时间前缀可用 + 可排序 + 数据库索引局部性」。

2. **`db.py`** — `ConversationDb` 抽象契约 + `PostgresConversationDb` + `FakeConversationDb`
   + `create_conversation_db(settings)`。
   六张表（conversations / conversation_turns / messages / agent_runs /
   agent_run_retrievals / agent_run_tool_calls），DDL 按 brief §7-8 逐字落地。
   幂等迁移：`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS`
   （legacy_thread_id 追加列 + 部分唯一索引）。`with self._connect() as conn, conn.transaction():`
   事务写法，psycopg dict_row，`_now()` ISO8601 UTC 时间戳。

3. **`store.py`** — `ConversationStore(db)` 领域服务 + `OwnershipError`。
   - `ensure_conversation`（UUID 直用 / legacy `t-…` 走 `legacy_thread_id` 映射复用）
   - `get_conversation`（UUID 或 legacy id，均校验 user_id）
   - `next_turn`（sequence_no = MAX+1，UNIQUE 冲突重试一次）
   - `add_user_message` / `add_assistant_message`（含 run_id、regenerated_from_message_id）
   - `set_message_status`（completed_at 置位）
   - `list_messages`（按 turn sequence_no、created_at 排序，含 regenerated_from 字段）
   - `list_message_versions`（同 turn 的 assistant 版本链，沿 regenerated_from 回溯）
   - `start_run` / `finish_run`（§8.1 字段；prompt_version 默认 `unversioned`，禁止 `unknown`）
   - `add_retrieval` / `add_tool_call`（§8.2/§8.3；input_redacted JSONB 序列化）
   - 所有带 user_id 的方法先校验所有权，不匹配抛 `OwnershipError`。

## TDD 证据

### RED（实现前，测试先行）

```
$ uv run pytest -q tests/unit/test_uuid7.py tests/unit/test_conversation_store.py
ERROR collecting tests/unit/test_uuid7.py
    ModuleNotFoundError: No module named 'careercrew_core.conversation'
ERROR collecting tests/unit/test_conversation_store.py
    ModuleNotFoundError: No module named 'careercrew_core.conversation'
2 errors
```

（编写测试后、实现前，包不存在 → 收集失败 = RED。）

### GREEN（实现后，聚焦 + 全量）

```
$ uv run pytest -q tests/unit/test_uuid7.py tests/unit/test_conversation_store.py
..........................                                                 [100%]   # 26 passed

$ $env:POSTGRES_TEST_DSN="postgresql://careercrew:careercrew@localhost:5432/careercrew_test"; uv run pytest -v tests/integration/test_conversation_pg.py
....                                                                      [100%]   # 4 passed

$ uv run pytest -q
496 passed, 12 skipped, 3 warnings in 139.81s
```

基线 470 passed + 8 skipped → 现 496 passed + 12 skipped
（+26 单元测试 passed、+4 集成测试 skipped[无 DSN] / 有 DSN 时 passed）。

### TDD 过程中真实捕获的 bug（集成测试价值）

1. **`user_id UUID` 类型约束**：集成测试用字符串 `u-…` 作 user_id，被真实 Postgres 的
   `invalid input syntax for type uuid` 拒绝 → 修正测试用 UUID，并确认 DDL 与 brief `user_id UUID` 一致。
2. **psycopg 原生 UUID 对象**：dict_row 把 UUID 列返回为 `uuid.UUID`（非 str），
   `_is_uuid(UUID_obj)` 抛 `AttributeError`，导致 UUID 会话被误判为 legacy →
   修正 `_row_to_dict` 把 UUID 归一为 str，`_is_uuid` 对 UUID 实例短路返回 True。
3. **JSONB input_redacted**：dict 直接绑定到 JSONB 列失败 → 修正为 JSON 字符串 + `::jsonb` 强转。
4. **动态 INSERT 占位符计数**：`insert_tool_call` 列/占位符/值数量不一致 → 修正。

## 文件清单

- `careercrew_core/conversation/__init__.py`（新增）
- `careercrew_core/conversation/uuid7.py`（新增）
- `careercrew_core/conversation/db.py`（新增）
- `careercrew_core/conversation/store.py`（新增）
- `tests/unit/test_uuid7.py`（新增）
- `tests/unit/test_conversation_store.py`（新增）
- `tests/integration/test_conversation_pg.py`（新增）

提交：`967639e feat(conversation): add conversations/turns/messages/agent_runs tables and store`
（仅暂存上述 7 个文件；未触碰 `careercrew_web` / `.superpowers/` 已存在的改动。）

## 自审发现

- **完整性**：brief §4 方法集全覆盖；legacy 映射（`legacy_thread_id` 追加列 + 部分唯一索引
  + `ensure_conversation` 复用）；`OwnershipError` 在带 user_id 的方法中首校验；`prompt_version`
  默认 `unversioned`（禁止 `unknown`）；所有时间列 TIMESTAMPTZ + ISO 序列化。
- **质量**：DB/Store 分层清晰，Store 不写 SQL；Fake 与 Postgres 接口一致；`_synchronized`
  串行化对齐 memory/db；`_row_to_dict` 归一 UUID。
- **YAGNI**：未接 API、未接 runtime（下一任务）；未加未需求的 retrieval 诊断列（chunk_hash 等）。
- **测试卫生**：单测用 Fake（26 个），集成测试用一次性库 `careercrew_test`
  （guard 拒绝生产库 `careercrew`），缺 `POSTGRES_TEST_DSN` 时 skip；全量输出 clean。

## 疑虑（concerns）

1. **`user_id UUID` vs 现状字符串 ID**：方案 DDL 用 `user_id UUID`，但现有 accounts 用
   `u_001` 字符串主键（`careercrew_api/auth/store.py` 硬编码 `u_001`）。方案内部也不一致
   （§7-8 DDL 是 UUID，例注 `owner_user_id = u_001` 是字符串）。T1.2 接线时若直接把
   `u_001` 写入 `user_id UUID` 会失败 —— 需要 T1.2 明确 user_id 是迁移为 UUID 还是 DDL 改 VARCHAR。
   本任务严格按 brief DDL（UUID）落地，此为 T1.2 的绑定决策，需上游确认。
2. **`set_message_status(message_id, status)` 无 user_id**：brief 方法签名不含 user_id，
   故该方法按 message_id 寻址更新（message_id 即能力），与其他「首校验 user_id」方法不同。
   这是 brief 明确签名的直接后果；若需所有权校验需在 T1.2 层补 user_id 入参。
3. **uuid7 跨进程唯一性**：进程内单调，跨进程靠随机尾（brief 允许「随机部分即可」）。
   并发多 worker 生成的 UUID 理论上可能碰撞（概率极低），如需强唯一可后续加 worker 熵。

## Fix Round (controller concerns)

控制器裁定（binding），对上述两个 concerns 的修复：

1. **`user_id` 列 → `VARCHAR(64) NOT NULL`（原 `UUID`）**
   - 理由：`auth_accounts` 用 TEXT id（`u_001`、`u_<hex>`）；DDL `user_id UUID` 与方案自身
     §5.2「保留现有账户 id、不重生成 UUID」矛盾。
   - 仅 `user_id` 列改 VARCHAR(64)；thread/turn/message/run id 仍为 UUIDv7（方案 §6）；
     `idx_conversations_user_updated` 保持 `(user_id, updated_at DESC)`。
   - 改动四张表：`conversations` / `conversation_turns` / `messages` / `agent_runs`
     （`agent_run_retrievals`、`agent_run_tool_calls` 已核对无 `user_id` 列，不改）。
   - 同步更新 `FakeConversationDb`（其 user_id 为 dict 字段，本就接受任意 str，无类型约束，无需改）。

2. **`set_message_status` → `set_message_status(user_id, message_id, status)`**
   - 签名按其他 store 方法顺序（user_id 在前）；所有权不匹配抛 `OwnershipError`。
   - `db.update_message_status` 契约与 Postgres/Fake 实现同步加 `user_id` 入参并做
     `WHERE id=%s AND user_id=%s` / `row["user_id"] == user_id` 所有权约束。
   - 更新单测调用点 + 新增 `test_set_message_status_rejects_wrong_owner`；
     集成测试改用 `u_001` / `u_002` 真实形状 id，并新增 set_message_status 所有权断言。

测试命令与结果：

```
$ uv run pytest tests/unit/test_conversation_store.py tests/unit/test_uuid7.py tests/integration/test_conversation_pg.py -q
...........................ssss                                          [100%]
# 27 passed, 4 skipped（无 POSTGRES_TEST_DSN，集成测试按预期 skip）

$ uv run pytest
497 passed, 12 skipped, 3 warnings in 98.68s
```

（+1 passed 来自新增的所有权单测；基线 496 + 1 = 497，全量绿。）

提交 SHA：`843dc53`（仅暂存 4 个文件：db.py / store.py / 两个测试；未触碰 careercrew_web 与
.superpowers 已存在的改动）。

## Fix Round (review findings)

三个 Important review findings 的修复：

1. **`retrieval_scope` 透传落地**（store.py ~:78）：`ensure_conversation` 的 `retrieval_scope`
   此前被接受却未传入 `upsert_conversation`。现线程化穿过 store → db 契约 →
   Postgres 实现：INSERT 增加 `retrieval_scope` 列，dict 用 `_json_dumps` 序列化 +
   `%s::jsonb` 强转（同 `input_redacted` 处理）；`ON CONFLICT` 用
   `retrieval_scope=COALESCE(EXCLUDED.retrieval_scope, conversations.retrieval_scope)`
   保留已存值。Fake 同步接受并保留 scope。新增单测
   `test_ensure_conversation_roundtrips_retrieval_scope` /
   `test_ensure_conversation_scope_preserved_on_reuse`。

2. **`set_message_status` 清空 completed_at**（db.py ~:362）：离开 `completed` 时现在显式
   `completed_at = NULL`（非 completed 分支传 None，直接 SET 而非 COALESCE，不再吞回旧值），
   `completed` 时置 now()。Fake 镜像同样行为
   （`row["completed_at"] = now() if completed else None`）。新增单测
   `test_set_message_status_clears_completed_at_on_non_completed`（completed→failed/cancelled）。

3. **`next_turn` 收窄异常捕获**（store.py ~:159）：不再 catch 裸 `Exception`。新增
   `SequenceCollision` 归一化信号：Postgres `insert_turn` 通过 `_is_unique_violation`
   （类型名 `UniqueViolation` 或 `sqlstate == "23505"`）把唯一冲突映射为 `SequenceCollision`
   并仅对该类型重试一次，其余异常原样上抛；Fake `insert_turn` 在
   `UNIQUE(thread_id, sequence_no)` 撞车时同样抛 `SequenceCollision`。新增单测
   `test_next_turn_propagates_non_collision_errors` 验证非冲突异常不被吞。

测试命令与结果：

```
$ uv run pytest tests/unit/test_conversation_store.py -q
........................................................................ [100%]
# 26 passed

$ $env:POSTGRES_TEST_DSN = uv run python -c "import re;raw=open('.env',encoding='utf-8').read();print(re.search(r'^DATABASE_URL=(.+)$',raw,re.M).group(1).strip().rsplit('/',1)[0]+'/careercrew_test')"; uv run pytest tests/integration/test_conversation_pg.py -q
....                                                                      [100%]
# 4 passed

$ $env:POSTGRES_TEST_DSN = <同上>; uv run pytest -q
513 passed, 3 warnings in 104.38s
```

（单元 26 passed；集成 4 passed[真实 Postgres 路径]；全量 513 passed、0 skipped —
基线 497 passed + 12 skipped，DSN 置位后 12 个集成/skip 测试实际运行通过，
另有 4 个本次新增/既有集成测试计 513。全量绿。）

> 注：运行集成前发现一次性库 `careercrew_test` 的 `conversations.user_id` 仍为旧的
> `uuid` 类型（843dc53 改 VARCHAR 后 `CREATE TABLE IF NOT EXISTS` 不迁移既有表），
> 导致 `u_001` 被拒。已 drop 该一次性库的 stale conversation 表让其按当前 DDL 重建；
> guard 确认非生产库 `careercrew`。

提交 SHA：`29c5649`（仅暂存 db.py / store.py / test_conversation_store.py /
t11-report.md；未触碰 careercrew_web / progress.md 等已存在改动）。
