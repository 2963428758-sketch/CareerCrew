# Task T3.4 — @ Context Reference（Mentions）报告

## 状态：DONE_WITH_CONCERNS

## 实现内容

### A. 后端

1. **`GET /api/context/resources`**（新 `careercrew_api/routers/context.py`，挂 `main.py`）
   - query：`types=knowledge,resume`（逗号分隔，缺省两者）、`q`（名称模糊，不区分大小写）
   - knowledge 走 `rt.list_context_resources`（runtime 新增）→ `store.list_docs(_knowledge_scope_filters(user_id, "all"))`
     （本人 private + public）；resume 走 `runtime._resume_library_items`（`data/parsed/resumes/{uid}/*/meta.json`，本人所有）
   - 返回 §15.1 形状：`{"items":[{"type","id","name","visibility"}]}`

2. **mentions 校验**（`careercrew_api/mentions.py`，纯模块）
   - `MentionRejected` 异常（语义=拒绝）；`resolve_mentions(user_id, mentions, knowledge_docs, resume_items)` 纯函数
   - knowledge_document：private → `owner_user_id == user_id`；public → `visibility == public`；伪造 public / 他人 private / 不存在 → 拒绝
   - resume → 本人所有（`resume_items` 已按 user_id 预过滤 + `resolve_mentions` 内再校验 `user_id == user_id`）
   - `runtime.resolve_mentions` 作为服务端胶水（先 `_ensure_heavy` → 拉可见集合 → 委托纯函数 → 返回 `as_dict()` 列表）

3. **knowledge.ask 强制上下文 + retrieval_source**
   - `schemas.KnowledgeAskRequest` 加 `mentions: list[Mention]`
   - `_run_knowledge_ask_stream_impl` 接收 `mentions`（resolved dict），提取 `knowledge_document` 的 id 为
     `forced_doc_ids`，经 `new_knowledge_advisor(forced_doc_ids=...)` → `_make_tools("knowledge", forced_doc_ids=...)`
     → `make_rag_query_tool(filters={"__access_user": user_id, "doc": forced_doc_ids})`（**强制上下文接缝**）
   - mentions 写入 user message metadata（`user_metadata={"category","scope","mentions"}`）
   - `agent_run_retrievals` 加列 `retrieval_source VARCHAR(30) NOT NULL DEFAULT 'auto'`（幂等迁移 `ADD COLUMN IF NOT EXISTS`，
     走 db.py `_ensure` 里 `SET lock_timeout='5s'` + `DO $$` 模式）；`add_retrieval(retrieval_source="auto")` +
     `chat_lifecycle.finish_turn` 透传；检索行 `doc ∈ forced_doc_ids → 'mention'`，否则 'auto'

4. **其他模块（match/plan/consult/interview）**：schemas 相应请求加 `mentions`；路由层 `_resolve_mentions`（chat/interview）
   或内联（consult）服务端校验（越权 → 422）；resolved mentions 写入对应 turn 的 user message metadata
   （`user_metadata={"mentions": [...]}`）。**本任务不做强制上下文注入**（报告说明，见下）。

### B. 前端

- `careercrew_web/src/lib/contextResources.ts`：`fetchContextResources`（GET resources、types/q 参数）+ `debounce` 纯函数 + 类型
- `careercrew_web/src/components/prompt/MentionPicker.tsx`：防抖搜索 → 下拉选择 → chips（可删），`onMentionsChange` 回调
- `PromptComposer.tsx` 加 `mentions?: ReactNode` 插槽（与 `attachments` 一致；页面接线 defer，见下）

## TDD 证据（RED → GREEN）

- **RED**：先写 `tests/unit/test_mentions.py`（10）与 `tests/api/test_context_resources_api.py`（7）、
  `test_observability_api.py` 的 retrieval_source 断言，运行失败/无生效。
- **GREEN**：
  - 后端全量（含 POSTGRES_TEST_DSN=…/careercrew_test）：**734 passed, 0 skipped**（基线 717 → +17）
  - 前端全量：**122 passed**（基线 112 → +10）；lint 0 error；tsc clean；build ok

## 强制上下文接缝说明

现有 `rag_query` 工具链路 `make_rag_query_tool(mm_search, filters=...)` → `mm_search.search(filters)` →
`QdrantStore._filter_expr` 已支持 `MatchValue`/`MatchAny`。**无需新增 doc-id 过滤参数**：
提知文档通过「在 knowledge 分支的 rag_query 附加 `filters["doc"] = forced_doc_ids`（list → `MatchAny`）」实现
最小强制上下文——把 mention 的 knowledge 文档限定为本轮检索白名单。resume 不在向量库，不参与 doc 过滤
（仅校验 + metadata 记录）。

## 其他模块 mentions 的 MVP 边界

match / plan / resume / consult / interview 的 mentions：**仅校验（越权 422）+ 写入 user message metadata**，
不做强制上下文注入、不影响各 agent 的实际检索/回答。依据：brief §15 明确「其他 chat 模块本任务不做强制上下文
注入（报告说明，reviewer 会看）」；强制上下文仅对 knowledge.ask（有明确 doc 向量白名单接缝）生效。
resume 的 `/generate` 与 `/chat`（`GenerateRequest`/`ResumeChatRequest`）**未加 mentions 字段**——不属于
brief 点名的「match/plan/consult/interview」模块，且避免扩大并行会话同区冲突面；如 reviewer 需要可后续补。

## 并行共存（同区域碰撞）

并行会话的「中文错误本地化 + display_name」改动与 T3.4 的 mentions 改动在 6 个共享文件行级交织
（`main.py`/`chat.py`/`consult.py`/`interview.py`/`knowledge.py`/`schemas.py`）。用 `git add -p`(`diff.context=1`)
逐 hunk 只暂存本人行；`main.py`「context 导入」与外国「RuntimeInitError+logger」骤邻合并 → 备份/checkout/只改本人
两行/恢复备份。**外国 hunk 完整保留在未暂存区**，未被打乱、未被提交。详见 `.superpowers/sdd/deferred/t34-coexistence.md`。

## 文件清单

后端（16，提交 d48a654）：`careercrew_core/conversation/db.py`、`store.py`、`careercrew_api/chat_lifecycle.py`、
`runtime.py`、`mentions.py`(新)、`routers/context.py`(新)、`routers/{chat,consult,interview,knowledge}.py`、
`schemas.py`、`main.py`、`tests/api/conftest.py`、`tests/unit/test_mentions.py`(新)、
`tests/api/test_context_resources_api.py`(新)、`tests/api/test_observability_api.py`。

前端（5，提交 9c68182）：`PromptComposer.tsx`、`MentionPicker.tsx`(新)、`MentionPicker.test.tsx`(新)、
`contextResources.ts`(新)、`contextResources.test.ts`(新)。

## 自审发现

1. **跨用户拒绝经真实 API 链验证** ✓：`tenant_api` fixture（真实 JWT 认证 + FakeRuntime）覆盖 B 引用 A 的
   private 文档 → 422、伪造 public → 拒绝。
2. **mention / auto 在 DB 可区分** ✓：`retrieval_source` 列，Fake + 真实 Postgres 幂等迁移均验证
   （734 passed 含 `test_conversation_pg.py` 真库路径）。
3. 纯函数 `resolve_mentions` 对 resume 补充 `user_id == user_id` 防御校验（不信任预过滤列表）。
4. 页面 send 逻辑接线（把 picker 的 mentions 带入请求体）**未提交**（defer，同 T3.2/T3.3 的 ChatPage 接线规则，
   避免与并行会话 ChatPage 重构冲突）——picker/lib 已自洽，接线由页面会话完成。

## 疑虑

1. 前端 mentions **未接线到任何页面**的 send 请求体（`PromptComposer.mentions` 插槽已备，但无页面注入
   `MentionPicker` 并把 `onMentionsChange` 的 mentions 写进请求）。属既定 defer 边界，但意味着功能端到端
   尚未可点用。
2. resume 的 `GenerateRequest`/`ResumeChatRequest` 未加 mentions（MVP 取舍，见上）。
3. 强制上下文仅覆盖 knowledge_document；resume mention 在 knowledge.ask 中仅 metadata 记录、不入检索。
4. 六个共享文件的外国 hunk 仍未提交（属并行会话责任）；若并行会话先提交后再合并，需留意同区三向合并。

## Fix Round (review findings)

修复评审三项 Important：

1. **强制上下文访问控制短路（defense-in-depth 缺口）**：`qdrant_store._filter_expr` 原来把 `__access_user` 展开为 Filter.should（无 min_should），与 doc 白名单 must 并存时被 Qdrant 视为 optional OR，访问控制仅靠上游 `resolve_mentions` 兜底。改为：存在其它 must 时把「public OR owner==user」作为嵌套 `Filter(should=[...], min_should=MinShould(..., min_count=1))` 并入 must，与 doc 白名单做 AND；仅有访问条件时保持原 should 形态不变。
2. **非 sink rag_query 的 retrieval_source 覆盖**：`_rag_query_retrievals`（matcher/resume/chat/regenerate 共用）与 knowledge 重跑路径显式补 `retrieval_source="auto"`，不再依赖 `finish_turn` 的兜底默认值。
3. **迁移注释与 DDL 不符**：`careercrew_core/conversation/db.py` ~290 注释改为描述实际行为（存量行被 `DEFAULT 'auto'` 回填；读侧对缺失/None 仍按 'auto' 兜底）。

### 测试命令与结果

覆盖测试（47 passed）：

```
uv run pytest tests/unit/test_mentions.py tests/unit/test_qdrant_store.py tests/api/test_context_resources_api.py tests/api/test_knowledge_ask_api.py tests/unit/test_chat_lifecycle.py tests/api/test_observability_api.py -q
```

全量（disposable DB，739 passed，exit 0，baseline 734 + 新增 5 测例）：

```
$env:POSTGRES_TEST_DSN = uv run python -c "import re;raw=open('.env',encoding='utf-8').read();print(re.search(r'^DATABASE_URL=(.+)$',raw,re.M).group(1).strip().rsplit('/',1)[0]+'/careercrew_test')"
uv run pytest -q
```

### 提交

`8f449f74dcb95f99b3c51031939aefdc6f529fcd` — fix(chat): enforce access constraint in forced-context filter and label all auto retrievals
