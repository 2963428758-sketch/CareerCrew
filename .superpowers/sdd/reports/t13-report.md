# Task T1.3 Report — 前端稳定-ID 管线 + 刷新恢复（Phase 1 验收）

## 1. What was implemented

### Backend（metadata JSONB 列 + store 参数 + 流 finish 写 metadata + 端点 payload）

- `careercrew_core/conversation/db.py`
  - `messages` 表追加 `metadata JSONB` 幂等迁移列（`SET lock_timeout` 包裹的 `DO $$ ... ADD COLUMN IF NOT EXISTS`，与既有 `legacy_thread_id` 迁移同模式）。
  - `ConversationDb.update_message_content` 抽象签名增加可选 `metadata=None`；Postgres 实现用 `COALESCE(%s::jsonb, metadata)` 实现「None=不动」语义。
  - `get_message` / `_read_message` / `list_messages` 的 SELECT 全部带上 `metadata` 列（dict 或 NULL）。
  - `FakeConversationDb` 同步：`insert_message` 行含 `metadata=None`，`update_message_content` 支持 metadata（None 不动）。
- `careercrew_core/conversation/store.py`
  - `set_message_content(..., metadata=None)`：新增可选 metadata 参数（None=不动），透传 db。
- `careercrew_api/chat_lifecycle.py`
  - `finish_turn(..., metadata=None)` 透传 `set_message_content`。
- `careercrew_api/runtime.py`
  - `_finish_chat_turn(ctx, content, status, metadata=None)` 透传。
  - `_run_knowledge_ask_stream_impl`：finish 时写 `metadata={"sources": capped}`。
- `careercrew_api/routers/consult.py`
  - `_finish_chat_turn(ctx, final, metadata={"opinions": opinions, "calls": calls})`。
- `careercrew_api/routers/threads.py`
  - `GET /api/threads/{id}/messages` 响应每条消息带上 `metadata`（dict 或 null）。

### Frontend（types / stores / restore helper / legacy remap / 6 页迁移）

- `src/types.ts`
  - `StreamEvent.done` 扩展 §9 稳定 ID 字段（`thread_id/turn_id/message_id/run_id/model/prompt_version/agent_version/status/legacy_thread_id`）。
  - `ChatMessage` 增加 `messageId?` / `turnId?` / `runId?`（后端稳定 ID）。
- `src/lib/historyRestore.ts`（新增，六页共用）
  - `parseThreadMessages` / `parseMemoryEntries` / `restoreHistory(tid)`：先读 `GET /api/threads/{tid}/messages`（非空即用，含稳定 ID + metadata），空时回退 `GET /api/memory`（无稳定 ID）。统一 `RestoredMessage` 形状。
- `src/store/streamStore.ts`
  - `StreamSession` 增加 `doneIds`（messageId/turnId/runId/threadId/legacyThreadId）。
  - done 分支：解析稳定 ID → 挂到 chatStore 最后一条 assistant 消息；legacy remap（`thread_id` ≠ 本地 id → `setThreadId` + `remapLegacyThread` + 流 session 重新挂到新 UUID）；`sessionKey` 可变变量保证 remap 后 patchS/初始化不残留旧 id。
- `src/store/threadStore.ts`
  - 新增 `remapLegacyThread(legacyId, newId)`：遍历各 module 线程条目 + `currentThreadByModule` + `completedUnread`，把旧 id 换成新 UUID。
- 六页迁移（`ChatPage/MatcherPage/ResumePage/KnowledgePage/InterviewPage/ConsultPage`）
  - 恢复逻辑统一改为 `restoreHistory(tid)`，各自投影到本地消息形状并挂 `messageId/turnId/runId`；knowledge/consult 另从 `metadata.sources` / `metadata.opinions+calls` 恢复富结构。
  - done 处理把 `stream.doneIds` 挂到该轮 assistant 消息。

## 2. TDD evidence（RED → GREEN）

- **Backend RED → GREEN**：先写 6 个新测试（`test_conversation_store.py::test_set_message_content_metadata_roundtrip` + `test_set_message_content_rejects_wrong_owner`、`test_chat_lifecycle.py::test_finish_turn_persists_metadata`、`test_stable_ids.py::test_knowledge_messages_include_metadata_sources` + `test_consult_messages_include_metadata_opinions`、`test_conversation_pg.py::test_set_message_content_metadata_roundtrip`）。首跑时 consult/knowledge 因 FakeRuntime 未透传 metadata 而 RED（`assert None is not None` / error 事件），修正 `tests/api/conftest.py` FakeRuntime 的 `_finish_chat_turn` 签名 + knowledge metadata 后 GREEN。
- **Frontend RED → GREEN**：先写 `historyRestore.test.ts`（6 tests，messages 非空/回退 memory/失败空数组）与 `streamStore.test.ts`（done 解析挂 ID / legacy remap 更新 store + session 重挂）。streamStore 的 remap 测试首跑 RED（session 仍残留旧 id，因 patchS 用固定 `threadId` 闭包），改为可变 `sessionKey` 后 GREEN。`threadStore.test.ts` 补 `remapLegacyThread` 两个用例。

## 3. Coexistence with parallel display_name changes

工作树含并行会话 display_name 未提交改动；我**未暂存、未覆盖**这些文件。我的前端改动与它们重叠了同一批 6 个页面文件，但**区域不冲突**：

- 并行改动区域：import（WorkspaceHeader→ConversationHeader）、`threadTitle` selector、Header JSX、`toolbar` 属性、EmptyState accent（KnowledgePage 的 `meta` usage → AgentDots，故 `const meta` 已由并行方移除）。
- 我的改动区域：`/api/memory` 恢复 useEffect、done 处理 useEffect、本地消息 interface、`import { restoreHistory }`（ChatPage/Matcher/Resume/Interview/Consult 移除不再使用的 `import { apiFetch }`，Knowledge/Resume 保留因仍用 apiFetch）。

我编辑且同时携带并行改动（已用 `git diff` 逐文件核对、TS/构建通过确认兼容）的文件：

- `careercrew_web/src/pages/ChatPage.tsx`
- `careercrew_web/src/pages/ConsultPage.tsx`
- `careercrew_web/src/pages/InterviewPage.tsx`
- `careercrew_web/src/pages/KnowledgePage.tsx`
- `careercrew_web/src/pages/MatcherPage.tsx`
- `careercrew_web/src/pages/ResumePage.tsx`

未发现同文件同区域冲突。

## 4. Files changed

### 我的文件（将暂存）
后端：
- `careercrew_core/conversation/db.py`
- `careercrew_core/conversation/store.py`
- `careercrew_api/chat_lifecycle.py`
- `careercrew_api/runtime.py`
- `careercrew_api/routers/consult.py`
- `careercrew_api/routers/threads.py`
- `tests/api/conftest.py`
- `tests/api/test_stable_ids.py`
- `tests/integration/test_conversation_pg.py`
- `tests/unit/test_chat_lifecycle.py`
- `tests/unit/test_conversation_store.py`

前端：
- `careercrew_web/src/types.ts`
- `careercrew_web/src/lib/historyRestore.ts`（新增）
- `careercrew_web/src/lib/historyRestore.test.ts`（新增）
- `careercrew_web/src/store/streamStore.ts`
- `careercrew_web/src/store/streamStore.test.ts`（新增）
- `careercrew_web/src/store/threadStore.ts`
- `careercrew_web/src/store/threadStore.test.ts`
- 六页 `.tsx`（同上）

### 并行改动（不暂存）
`careercrew_api/auth/*`、`careercrew_api/schemas.py`、`tests/api/test_auth_api.py`、`tests/fakes.py`、`careercrew_web/src/components/{KnowledgePanel,ResumePanel,UserMenu}.tsx`、`components/app-shell/AppSidebar.tsx`、`lib/auth.ts`、`pages/SettingsPage.tsx`、`components/DisplayNameEditor.tsx`、`components/conversation/ConversationHeader.tsx`、`.superpowers/sdd/progress.md`、`.superpowers/sdd/reports/t01|t03-report.md`。

## 5. Self-review findings

- **偏差（需知会）**：brief §5 写 `id?`（message_id），我采用了「保留既有 `id` 作为 UI key/anchor，另加 `messageId/turnId/runId` 三个稳定 ID 字段」的实现，而非把 `id` 重构为可选 message_id。理由：`id` 同时承担 React key / turn 分组 / `data-turn-anchor` DOM anchor（`useActiveTurn` 的 IntersectionObserver 依赖）/ regenerate 过滤 / `FeedbackArea` 绑定共五重职责；直接改可选会波及全六页 turn 分组与锚点，超出「最小改动」。§2.2 明文「message_id 绑定、禁止前端生成 message ID」，验收标准也用 `message_id/turn_id/run_id` 命名，故本实现与验收一致。
- **legacy remap 的流 session 重挂**：done 返回 UUID 且 ≠ 本地 id 时，除更新 chatStore/threadStore，还把流 session 重挂到新 id（并用可变 `sessionKey` 让后续 `patchS` 不再误写旧 id）。这是让页面按新 id 仍能查到该 done 流的关键修复（TDD 捕捉到）。
- YAGNI：未引入新 Store、未做 feedback 持久化、未做 regenerate（T1.6 范围）；metadata 只写了 sources/opinions/calls 三种实际存在的富结构。
- 测试卫生：新增后端 6 + 前端 10 用例；基线 539→545、前端 20→30 全绿。

## 6. Concerns

1. **`id` 语义偏差**（见上 §5）——若 controller 坚持 `id` 本身必须是 message_id（可选），需二轮重构六页 turn 分组与 anchor，成本显著。已按 §2.2 + 验收命名采用 `messageId` 字段。
2. **流式期间的 user 消息无稳定 ID**：符合 brief（`用户消息的 id 后端不通过 done 返回`），刷新后由 messages 端点补齐；流式中途刷新则该 user 消息稳定 ID 不可得（可接受，brief 已声明）。
3. **remap 与「未在看会话完成」的 unread 圆点**：remap 后 `markCompletedUnread` 用新 id；旧 id 上的 unread 由 `remapLegacyThread` 迁移。若 done 的 `legacy_thread_id` 存在但 `thread_id` 未变（理论上不存在），无动作。
4. **metadata 列**：生产库若 messages 表已存在，`_ensure()` 幂等 ALTER 会补列（NULL 默认），历史行 metadata 为 NULL；前端 restore 对 NULL 已兜底。

## 7. Test summary

- 后端：`uv run pytest`（POSTGRES_TEST_DSN=.../careercrew_test）= **545 passed**（基线 539，+6）。
- 前端：`npx vitest run` = **30 passed**（基线 20，+10）；`npm run lint` 0 errors；`npx tsc -b` clean；`npm run build` ok。

## Fix Round (review findings)

针对 review「Needs fixes」四条的修复轮，commit `b2212f9`。

### Changes

1. **Critical 1 — streamStore remap 重挂 controllers/thinkTimers**（`src/store/streamStore.ts`）
   - `armThinking`/`disarmThinking`、`controllers.set`、`finally` 里的 `controllers.delete` 全部改用可变 `sessionKey`（原来用闭包 `threadId`）。
   - remap 分支在 `sessionKey = evt.thread_id` 之前，把在途 `controller` 与 `thinkTimers` 里 `sessionKey` 键下的条目 `delete` + 搬到新 UUID，保证 `stop(newId)` 能 abort 在途 fetch、thinking timer 不残留旧 id。
   - 新增 vitest 用例 `remap 后 stop(新 UUID) 能 abort 在途请求`：done 触发 remap 后二次 read 挂起，`stop("uuid-new")` 命中 re-key 后的 controller，断言 `signal.aborted === true`。

2. **Important 2 — 恢复 Interview 评分写回**（`src/pages/InterviewPage.tsx`）
   - 重新引入 `qaList` state、`pendingRef`（题目↔作答配对）、`handleRecord`（`POST /api/interview/record`）、`import { apiFetch }` + `import type { InterviewQA }`。
   - done effect 里恢复 `stream.doneScore`/`doneFeedback` 写回（`patch.score/feedback` + `setQaList`），并保留新稳定 ID 字段（`messageId/turnId/runId`）与 restore 路径不变。
   - `send()` 恢复 `pendingRef` 赋值；会话切换/新建 effect 恢复 `pendingRef`/`qaList` 清零。
   - header 用 `HeaderIconAction`（`Check` 图标）注入「保存 N 条到记忆」，与并行方的 `ConversationHeader` 结构兼容。

3. **Important 3 — ConsultCall 类型对齐存储形状**（`src/types.ts` + `src/pages/ConsultPage.tsx`）
   - `ConsultCall.round`/`task` 改为可选（存储的裸 `consult_calls` 字典异常兜底时只写 `{content}` 或首轮无 `task`），仅 `agent`/`content` 必填。
   - ConsultPage 调度分组 `reduce` 用 `call.round ?? 0` 兜底，第 0 轮文案显示「调度过程」。

4. **Minor 4 — unread 顺序注释**（`src/store/streamStore.ts`）
   - 在「completed while not viewing」判断前补注释，说明其必须位于 remap 之后读取 `currentThreadByModule` 的原因（避免当前正在看的 remap 会话被误打未读圆点）。

### Test commands + results（前端；后端本次无改动，未跑 pytest）

- `npx vitest run` = **31 passed**（基线 30，+1 新增 abort 用例：11 files）。
- `npm run lint` = 0 errors（2 个 pre-existing 警告，非本次引入）。
- `npx tsc -b` = clean。
- `npm run build` = ok（vite 8.2.1，built in ~1s）。

### Commit

- `b2212f9 fix(web): re-key stream controllers on remap, restore interview scoring, align consult call types`（5 files：streamStore.ts / streamStore.test.ts / types.ts / InterviewPage.tsx / ConsultPage.tsx）。

### Coexistence（并行 display_name 改动）

- 仅暂存我改动的 5 个文件；`ChatPage/MatcherPage/ResumePage/KnowledgePage` 及其余 display_name 文件（`auth/*`、`components/*`、`SettingsPage` 等）未暂存、未覆盖。
- `InterviewPage.tsx`/`ConsultPage.tsx` 同时携带并行方的 `ConversationHeader` 改动，我以当前工作树为基点做增量编辑，未回退并行方区域。
