# Task T2.3 报告 — 会话菜单（Rename / Export MD+JSON / Clear / Delete）+ threads CRUD API

分支 `feature/agent-feedback-eval`。两个提交：
- `bb1c10f` `feat(chat): thread rename export clear delete endpoints`
- `5b30449` `feat(web): conversation menu with export and confirm dialogs`

## 一、实现了什么

### 后端（`bb1c10f`）

1. **ConversationDb 扩展**（`careercrew_core/conversation/db.py`）：抽象契约 + Postgres + Fake
   三处同步新增：
   - `update_title(user_id, conversation_id, title)`
   - `clear_conversation(user_id, conversation_id) -> int`（删 turns 级联 messages，
     并清 runs/retrievals/tool_calls；**保留 conversation 行**，返回删除的 turn 数）
   - `delete_conversation(user_id, conversation_id) -> bool`（全删 conversation + 子表）
   - `list_runs(user_id, thread_id) -> list[dict]`（按 created_at 升序）
2. **ConversationStore 扩展**（`store.py`）：`rename_title` / `clear_conversation` /
   `delete_conversation` / `list_runs`，全部先经 `_require_owned` 做所有权校验
   （不匹配/不存在 → `OwnershipError`）。
3. **导出纯函数**（`careercrew_core/conversation/export.py`）：
   - `build_markdown(conv, messages)`：`# Title` → `## User` / `## Assistant` → `### Sources`
   - `build_json(conv, messages, runs)` → dict：`{thread, messages, sources,
     runs:[{model, prompt_version, agent_version, latency_ms}]}`
   - `build_json_text(...)`：序列化文本版（路由直接返回）
   - **敏感字段红线**：字段白名单（run 只取 4 个字段；消息只取 role/content/sources；
     剔除 run_id/regenerated_from_message_id/metadata 原样），另加 `_assert_no_sensitive`
     哨兵（token/api_key/secret/system_prompt/credential）兜底拒绝，命中即抛 ValueError。
4. **路由**（`careercrew_api/routers/threads.py`）：
   - `PATCH /threads/{thread_id}`：兼容 legacy data.py PATCH 语义
     （title/pinned/module/retrieval_scope 经 `rt.touch_thread` 更新 thread_store）；
     仅当 title 非空时同步 conversation 表（§13.1 双 store 一致）。非法范围仍 422、
     跨用户/不存在 → 404。
   - `DELETE /threads/{thread_id}`：`delete_conversation` 全删 + 同步
     `rt.delete_thread`（legacy thread_store + 情景事件），跨用户/不存在 → 404。
   - `POST /threads/{thread_id}/clear`：`clear_conversation` 清空消息，保留会话/标题。
   - `GET /threads/{thread_id}/export?format=md|json`：无 conversation 行 → 404；
     非法 format → 400。

### 前端（`5b30449`）

1. **`careercrew_web/src/lib/conversationExport.ts`**：纯函数 `buildMarkdown` /
   `buildJson` / `downloadBlob`（Blob 下载）。前端兜底与测试用；生产导出走后端。
2. **`careercrew_web/src/components/conversation/ConversationMenu.tsx`**：自包含「⋯」
   下拉菜单——Rename（内联输入）/ 复制会话 ID / 导出 Markdown / 导出 JSON /
   清空消息（ConfirmDialog 二次确认）/ 删除会话（ConfirmDialog 二次确认）。
   导出走后端 `GET /export`；清空走后端 `POST /clear`；重命名/删除复用 `threadStore`。

## 二、TDD 证据（RED → GREEN）

### 后端 RED

先写测试再实现：
- `tests/unit/test_conversation_store.py` 新增 14 用例 → `AttributeError: no attribute
  'rename_title'/'clear_conversation'/'delete_conversation'/'list_runs'`（14 FAILED）。
- `tests/api/test_threads_menu_api.py`（5 用例，含跨用户 404 / 敏感字段 / 无 conversation 404 /
  非法 format 400 / 空会话 clear）+ `tests/unit/test_conversation_export.py`（9 用例）。

### 后端 GREEN

- 焦点：`uv run pytest tests/unit/test_conversation_store.py tests/unit/test_conversation_export.py
  tests/api/test_threads_menu_api.py` → 全绿。
- 全量（POSTGRES_TEST_DSN 指向 careercrew_test）：**643 passed**（基线 617 → +26）。

### 前端 RED → GREEN

- `conversationExport.test.ts`（4）+ `ConversationMenu.test.tsx`（6）初跑见类型/交互失败，
  修组件 renaming 状态机（点「重命名」保持菜单开启进入内联输入）后全绿。
- 全量 `npx vitest run`：**78 passed**（基线 68 → +10）。
- `npm run lint`：0 errors（仅 `ui/button.tsx` 既有 2 条 no-unused 警告，非本任务引入）。
- `tsc -b` 干净；`npm run build`（vite build）成功。

## 三、export 回退决策

**选择：无 conversation 行的旧线程 → 404，不做 episodic 回退。**

理由：
- brief 方案原文明示「实现复杂度高则先 404 并在报告说明」；
- episodic（/api/memory 同源）数据形状与 conversation 表不一致（`text`/`sources` 扁平
  包裹、无 run 模型/版本/latency 字段），拼装会引入两套导出 code path，且 §13.3 要求
  的 `runs:[{model,prompt_version,agent_version,latency_ms}]` 在 episodic 侧基本缺失；
- 404 语义清晰（用户明确知道旧线程不可导出），不静默产出残缺导出。
  Reviewer 如需 episodic 回退，可作为 Phase 3 增量（复用 `rt.memory_list`）。

## 四、并行共存 / deferral 日志

- 工作树含并行会话未提交改动（display_name / 错误本地化 / ConversationHeader / 6 页面）。
- 我**只触碰自己的文件**：`db.py`/`store.py`/`export.py`/`threads.py`/三个测试文件 +
  前端 lib + ConversationMenu 组件与测试。未改动任何并行会话文件（`git diff` 逐一确认，
  `threads.py` 在我改前是 clean 的）。
- **header 集成 defer**：`ConversationHeader.tsx` 与 6 个页面属并行会话未提交改动；
  我的 `ConversationMenu` 设计为**独立触发器**（不依赖改 header），可通过
  `ConversationHeader` 已有的 `extra` prop 注入，零行级冲突。按 T2.1 模式，组件+hook
  独立提交，页面接线留工作树，接线说明备份到
  `.superpowers/sdd/deferred/t23-header-wiring.md`（gitignore 目录，同 T2.1 的 .patch）。
- 未 `git add -A`；每个提交只 stage 目标文件（后端 7 文件、前端 4 文件）。

## 五、文件清单

后端（`bb1c10f`）：
- `careercrew_core/conversation/db.py`、`store.py`、`export.py`
- `careercrew_api/routers/threads.py`
- `tests/unit/test_conversation_store.py`、`tests/unit/test_conversation_export.py`、
  `tests/api/test_threads_menu_api.py`

前端（`5b30449`）：
- `careercrew_web/src/lib/conversationExport.ts`（+ test）
- `careercrew_web/src/components/conversation/ConversationMenu.tsx`（+ test）

工作树备份（不入库）：`.superpowers/sdd/deferred/t23-header-wiring.md`
报告（本文件）：`.superpowers/sdd/reports/t23-report.md`

## 六、自审发现

- **良好**：
  - export 字段白名单 + 敏感哨兵双重防线，测试显式断言无 token/api_key/system_prompt；
  - 跨用户四类端点全部 404（`test_cross_user_404_for_all_menu_endpoints`）；
  - clear 保留 conversation/title、清空消息（`clear_keeps_conversation_removes_messages_and_turns`）；
  - rename 双 store 一致（conversation + thread_store）在 API 级断言。
- **Minor（遗留，不阻塞）**：
  1. PATCH 路由为兼容 legacy 语义，把 `title/pinned/module/retrieval_scope` 全走
     `touch_thread`，title 才额外同步 conversation 表；若纯 legacy 线程（无 conversation 行）
     被 rename，conversation 侧静默跳过（符合既有行为，但双 store 在该边界不一致）。
  2. `clear`/`delete` 是同步硬删（单事务），方案 §13.4/§13.5 建议的"逻辑删除 + 异步
     job"未做——本任务同步删保证一致性，异步清理属 Phase 3 优化。
  3. 前端 `ConversationMenu` 未接线到页面（defer），故菜单实际不可见——需 reconciliation
     时按 `t23-header-wiring.md` 落地。

## 七、疑虑

1. **delete 后 legacy thread_store 的失败吞异常**：与既有 `create_thread` 的
   `register_thread` 失败吞异常一致，避免 conversation 删除成功却因 sidebar 元数据
   清理失败而返回错误；但可能出现 conversation 已删、sidebar 仍残留的短暂不一致
   （下次 fetch 会以 conversation 缺失 + thread_store 残留为准，需确认 sidebar 列表
   是否会自动剔除——目前 thread_store 残留的线程仍会在 GET /api/threads 列出）。
2. **PATCH 语义合并**：把 §13.1 rename 与 legacy PATCH（pinned/scope/module）合并在一个
   路由里，行为正确但有语义耦合；若后续需拆分，需同步调整前端 `threadStore.setThreadScope`
   等调用方（它们依赖同一 PATCH 端点）。

## Fix Round (review findings)

Review verdict「Needs fixes」的修订，针对 T2.3 后端路由与持久化层：

### 变更

1. **Critical 1 — legacy-only 线程 DELETE 回归**（`careercrew_api/routers/threads.py`
   `delete_conversation`）：恢复 legacy data.py DELETE 语义。改为先跑
   `rt.delete_thread`（legacy thread_store + 情景事件），失败即中止、错误上抛（无部分
   删除）；随后删 conversation 行——无 conversation 行（纯 legacy 线程）时吞
   `OwnershipError` 仍算成功；若无 legacy 元数据但存在 conversation（conversation-only）
   也成功删除；两者皆无或跨用户 → 404。
2. **Important 2 — rename 同步吞异常**：`rename_thread` 的 `except Exception: pass`
   收紧为仅 `OwnershipError`（纯 legacy 线程）静默跳过；其余异常（DB 等）上抛，title
   分歧不再被静默接受。
3. **Important 3 — delete 失败被吞**：见第 1 条——`rt.delete_thread` 先执行，失败上抛，
   conversation 删除置后，杜绝「conversation 已删、legacy 清理失败」的部分删除状态。
4. **Minor 4 — `regeneration_keys` 孤儿清理**（`careercrew_core/conversation/db.py`）：
   `clear_conversation` 事务内、删除 messages 前先执行
   `DELETE FROM regeneration_keys WHERE message_id IN (SELECT id FROM messages WHERE
   thread_id=… AND user_id=…)`（作用域限定受影响 thread 的消息）；`delete_conversation`
   复用 `clear_conversation` 故同样覆盖；Fake 实现一致。新增
   `test_clear_removes_orphaned_regeneration_keys` / `test_delete_removes_orphaned_regeneration_keys`
   以及 API 级 `test_delete_legacy_only_thread` / `test_delete_conversation_only_thread` /
   `test_delete_missing_thread_404`。
5. **Minor 6 — 过期注释**（`careercrew_api/main.py`）：更正 PATCH/DELETE /api/threads
   归属说明（threads.py 先注册遮蔽 data.py 旧路由）。

### 测试命令与结果

- 聚焦：
  `uv run pytest tests/api/test_threads_menu_api.py tests/api/test_regenerate_api.py
  tests/unit/test_conversation_store.py -q` → 63 passed（1 次迭代修正 store 层
  `reserve_regeneration` 签名后全绿）。
- 全量（`$env:POSTGRES_TEST_DSN` 指向 careercrew_test）：
  `uv run pytest -q` → exit 0，100% 通过，**648 passed**（基线 643 → +5）。

### commit

`fix(chat): legacy thread delete fallback, strict sync errors, regeneration key cleanup`
— `9649bb3`。
