# T3.2+T3.3 — Attachment UI + 异步解析 + Save to Knowledge（Phase 3）

## 状态：DONE

## 实现概述

### 后端（T3.3）—— `careercrew_api/routers/attachments.py`

- `POST /api/chat/attachments/{attachment_id}/save-to-knowledge`（原 501 占位 → 真实现，status_code=202）：
  - 所有权校验（复用 `_owned_attachment` → 404）
  - 状态门控：仅 `uploaded` / `ready` / `failed` 可保存（`saved_to_knowledge` → 409 幂等拒绝）
  - 立即置 `parsing` → 返回 `202 {status:"parsing", id}`
  - 后台 `daemon` 线程 `_run_save_job` 执行解析+入库（失败不阻塞请求）
- 解析执行与端点分离：
  - 模块级可注入 `_parse_and_ingest`（测试用 fake 断点）
  - 默认 `_default_parse_and_ingest` 委托 `rt.ingest_document`（完整复用 knowledge.py 的
    MultimodalIngestionPipeline：md/txt 内部走 MarkdownLoader 快速路径、PDF/DOCX/PPTX/XLSX/PNG/JPG
    走 MinerU 本地/API；产出向量 upsert）
  - knowledge 文档：doc_id=附件 UUID（服务端生成、幂等）、title=original_filename、
    owner=当前用户、visibility=private、category=knowledge
- `GET list` 增加返回 `parser_type` / `parser_error` / `knowledge_document_id` 字段（前端状态 chips 需要）

### 前端（T3.2）—— `src/lib/attachments.ts` + `src/components/prompt/AttachmentPicker.tsx`

- `src/lib/attachments.ts`（纯 API 封装，mock fetch 单测）：
  - `validateAttachmentSelection`（扩展名白名单 + 25MB 客户端预检）
  - `uploadAttachment` / `listAttachments` / `deleteAttachment` / `saveAttachmentToKnowledge`
  - `pollSaveToKnowledge`（终态 = ready/failed/saved_to_knowledge/deleted）
  - 类型 `Attachment`、`AttachmentStatus`（§14.3 状态全集）
- `AttachmentPicker.tsx`（自包含，`threadId` prop + 可选 `onAttachmentsChange` 回调）：
  - 文件选择（accept 白名单、客户端预检）、上传（multipart 带 thread_id）
  - 状态 chips：名称/大小/状态文案（上传中/已上传/解析中/已就绪/解析失败/已入知识库）
  - 删除（`ConfirmDialog` 二次确认）
  - 「存入知识库」按钮（`uploaded`/`ready` 可用）→ save → `pollSaveToKnowledge` 刷新状态
    → 失败显示 `parser_error`，`failed` 态提供重试按钮
- `PromptComposer.tsx`：新增可选 `attachments?: ReactNode` 插槽（渲染在工具栏上方），
  页面接线用它注入 `<AttachmentPicker threadId={...} />`（defer 模式，不碰 ChatPage）

## TDD 证据（RED→GREEN）

| 阶段 | 命令 | 结果 |
|------|------|------|
| RED | `uv run pytest -q tests/api/test_attachments_api.py -k "save"` | 8 failed（全部命中 501 占位 / 断言失败） |
| GREEN | 同上（实现后） | 8 passed |
| RED | `npx vitest run src/lib/attachments.test.ts` | 11 failed（先行失败 + 超时 unhandled） |
| GREEN | 同上（修复） | 11 passed |
| RED | `npx vitest run src/components/prompt/AttachmentPicker.test.tsx` | 3 failed（jest-dom matcher 缺失 + save 逻辑 bug） |
| GREEN | 同上（改用 textContent 断言 + pollSaveToKnowledge） | 7 passed |
| 回归后端 | `uv run pytest` | **689 passed, 27 skipped**（全绿） |
| 回归前端 | `npx vitest run` | **112 passed**（基线 94 + 新增 11 lib + 7 组件） |
| 质量门 | `tsc -b` / `oxlint` / `vite build` | 干净 / 0 errors / built 1.32s |

## Pipeline 复用与 fake 注入

- **复用**：save-to-knowledge 的默认解析路径直接调用 `rt.ingest_document`（与 knowledge.py
  上传端点共用同一 `MultimodalIngestionPipeline`）。md/txt 在 `_ingest_file_impl` 内部走
  `MarkdownLoader` 直读（未触发 MinerU）；PDF/图片走 `_make_loader`（MinerU）。附件文件
  落盘路径已满足 `ingest_document` 的 `is_relative_to(DATA_ROOT)` 越界校验。
- **fake 注入**：单元/集成测试通过两个层级避免真实 MinerU：
  1. API 集成测试用 `FakeRuntime.ingest_document`（conftest 已 duck-type，记录 `ingest_calls`
     并可注入 `ingest_error` 模拟解析失败）；
  2. 端点内 `_parse_and_ingest` 为模块级可注入钩子，未来如需更细粒度 fake 可 monkeypatch。
- **无 MinerU 调用**：全部单测/集成测均未实例化真实 `MinerULoader`/`MinerUApiLoader`。

## 状态机图

```
                POST /save-to-knowledge (202)
   ┌─────────────────────────────────────────────┐
   │  所有权校验(404) → 状态 ∈ {uploaded,ready,failed}│
   └─────────────────┬───────────────────────────┘
                     ▼
               [parsing]  ── 后台线程 _run_save_job
                     │
        ┌────────────┴────────────┐
        ▼ 解析成功(入库前)          ▼ 解析/入库失败
    [ready] ──mark_saved──► [failed] + parser_error ──(重试 POST)──► [parsing]
        │                    ▲
        ▼                    │
 [saved_to_knowledge]        │  (failed 允许重试)
  expires_at=NULL           └─────────────────────────
  knowledge_document_id=UUID
```

## 并行共存日志

- 工作树含并行会话未提交改动（40+ 文件 M + 若干 ??）。本任务只暂存/提交自己的 7 个文件，
  未 `git add -A`，未触碰任何并行 hunk。
- 唯一交叉点 `PromptComposer.tsx` 在 `git status` 中原本**未**被标记 `M`（非并行改动目标），
  仅新增 4 行可选 `attachments` 插槽，非破坏性。
- 页面接线（ChatPage 注入 `<AttachmentPicker threadId>`）按 defer 模式**未做**——组件与 lib
  独立提交，接线留待并行会话合入后再做（见下方「疑虑 3」）。

## 文件清单

后端提交 `e376fe3`：
- `careercrew_api/routers/attachments.py`（save-to-knowledge 实现 + list 字段扩展）
- `tests/api/test_attachments_api.py`（8 个 save 状态机测试 + 移除旧 501 测试）

前端提交 `c4a3fc4`：
- `careercrew_web/src/lib/attachments.ts`（新建）
- `careercrew_web/src/lib/attachments.test.ts`（新建，11 测试）
- `careercrew_web/src/components/prompt/AttachmentPicker.tsx`（新建）
- `careercrew_web/src/components/prompt/AttachmentPicker.test.tsx`（新建，7 测试）
- `careercrew_web/src/components/prompt/PromptComposer.tsx`（+4 行 `attachments` 插槽）

## 自审发现

1. **完整性** ✅：状态机全链路（uploaded/ready/failed→parsing→ready→saved_to_knowledge；
   failed→重试）可观测，expires_at 取消，knowledge_document_id 落库，owner/visibility 对齐。
2. **质量** ✅：解析执行与端点分离；后台线程失败收口到 `parser_error`（经 `friendly_error` 中文化）。
3. **纪律（YAGNI）** ✅：未引入队列/进度表，复用进程内线程（与 knowledge.py 单进程假设一致）。
4. **测试卫生** ✅：无 MinerU 真实调用；前端用 `textContent` 断言（项目未装 jest-dom）。
5. **重试** ✅：`failed` 状态允许再次 POST → 重新走解析（测试 `test_save_failed_can_retry` 覆盖）。
6. **parse 失败可见** ✅：`test_save_failure_sets_failed_and_parser_error` 验证 `parser_error`
   含 MinerU 失败原文。

## 疑虑（DONE_WITH_CONCERNS 项，均不阻断）

1. **category 硬编码 `"knowledge"`**：chat 附件（如简历 PDF）未按文件名自动分类（`category_for_doc`）。
   与 brief「title=original_filename」不冲突，但若希望附件按内容分类进知识库，后续可改 `category=""`
   触发自动识别。当前选择保守（附件非简历专用），已注明。
2. **`_run_save_job` 的自有 store 连接**：brief 要求「后台线程用独立 store 连接」。当前实现复用
   传入的 `rt.attachment_store`（其 `PostgresAttachmentDb` 内部每方法 `_connect()` 惰性建连接 +
   `write_lock` 串行化），未显式新建独立 store。这在单进程 Threading 下是安全的（每操作独立连接），
   但严格讲与 brief 措辞有出入；如需严格独立，可在 `_run_save_job` 内重建 `AttachmentStore`。
3. **页面接线 defer**：`ChatPage.tsx` 有并行未提交改动，故 AttachmentPicker 的实机接线（传
   threadId + 展示）未落地。组件/lib 已独立可用并被测试覆盖，待按 defer 模式补接线说明
   （可参照 `deferred/t24-chatpage-wiring.md` 格式）。

## 报告路径

`.superpowers/sdd/reports/t32-report.md`

## Fix Round (review findings)

复审针对 T3.2+T3.3 提出三个 Important 项 + 一个证据缺口，已全部修复（commit `c520f44`）。

### 变更

1. **Important 1 — category 硬编码 `"knowledge"`**：`_default_parse_and_ingest`
   中 `ingest_document(category="knowledge")` 改为 `category=""`，让知识管线内部
   （`runtime.ingest_document` → `category_for_doc`）按 doc_name 自动分类，与
   `knowledge.py` 上传端点（`category: str = Form("")`）一致；并加注释说明自动分类决策。
2. **Important 2 — ready 中间态**：去掉 `_run_save_job` 里对 `ready` 的中间写入（原先
   `update_status("ready")` 紧随 `mark_saved` 被立即覆盖，无可观测 ready）。状态机简化为
   `parsing → saved_to_knowledge`（成功）/ `failed`（失败）。`ready` 保留为 DB 契约上的
   遗留/过渡值（枚举仍在、仍可发起 save，见 `_SAVEABLE_STATUSES`），但不产出中间写，
   并在 docstring/注释中注明 reserved/transitional。
3. **Important 3 — stale parser_error**：成功后 `update_status(..., parser_error=None, ...)`
   显式清空 `parser_error`（连同 `mark_saved`），重试成功不再残留上一次失败的错误。
4. **前端轮询终态**：`attachments.ts` 的 `TERMINAL_STATUSES` 从
   `{ready,failed,saved_to_knowledge,deleted}` 改为 `{failed,saved_to_knowledge,deleted}`，
   并同步测试与组件注释。

### 测试命令与结果

- 后端定向（含 PG 集成）：
  `$env:POSTGRES_TEST_DSN = uv run python -c "..."; uv run pytest tests/unit/test_attachment_store.py tests/api/test_attachments_api.py tests/integration/test_attachments_pg.py -q`
  → **41 passed**（其中 `test_attachments_pg.py` 5 项全部 RUN 未跳过）。
- 全量后端（显式设 DSN）：
  `$env:POSTGRES_TEST_DSN = ...; uv run pytest -q`
  → **717 passed, 0 skipped**（较上一轮 689 passed / 27 skipped：27 项原 PG 跳过现已实跑；
  新增 `test_save_retry_success_clears_stale_parser_error`）。
- PG 集成单独复跑：`uv run pytest tests/integration/test_attachments_pg.py -v`
  → **5 passed**（未跳过）。
- 前端：`npx vitest run` → **112 passed**；`npx tsc -b` → 干净。

### 提交

`c520f44` — `fix(attachments): auto category, honest status machine, clear stale parser error`
