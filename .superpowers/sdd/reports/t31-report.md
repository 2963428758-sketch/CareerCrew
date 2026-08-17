# Task T3.1 报告 —— Attachment API（upload/validation/storage/TTL）

## 状态
DONE

## 提交
`c07c997` — `feat(chat): attachment upload validation storage and ttl lifecycle`
（13 files，+1554/-1）

## 实现内容

### 1. 校验模块（纯函数，无新依赖）
`careercrew_core/conversation/validation.py`
- `validate_attachment(filename, mime, content_head, size) -> {extension, mime}`
- `EXTENSION_WHITELIST`（9 种 §14.1）、`MIME_TO_EXTENSION`（MIME→扩展名白名单映射）
- `MAX_ATTACHMENT_SIZE = 25MB`；`AttachmentValidationError`
- 校验维度（§14.1 全部）：扩展名白名单、MIME 白名单 + 扩展名↔MIME 一致性、
  magic-byte 签名、size 上限、文本类（md/txt）UTF-8 可解码兜底
- 归一化：扩展名/MIME 小写；`.jpg`/`.jpeg` 同族互配特例

### 2. 表 + Store（与 conversation 同库）
`careercrew_core/conversation/attachments.py`
- `chat_attachments` 表（§14.4 DDL，`user_id`/`thread_id` VARCHAR(64) 一致化——方案
  原 DDL 的 UUID 与现有 `u_001` 账号体系矛盾，对齐 conversation 包既有决策）
  列：id UUID PK、user_id、thread_id、original_filename(500)、storage_key(1000)、
  mime_type(150)、size_bytes BIGINT、status(30)、parser_type(100)、parser_error TEXT、
  knowledge_document_id UUID、created_at、last_used_at、expires_at（均 TIMESTAMPTZ）
- `AttachmentDb`（ABC）+ `PostgresAttachmentDb` + `FakeAttachmentDb`
- `AttachmentStore.create/get/list_attachments/count_nondeleted/update_status/delete/
  mark_saved/expired_attachments`
- `create_attachment_db(settings)`（backend=fake → Fake；否则 Postgres，复用
  memory.postgres.dsn）
- 默认 `expires_at = now + 7d`（§14.5）；`mark_saved` → `expires_at=NULL` +
  status=saved_to_knowledge（取消 TTL）

### 3. 路由
`careercrew_api/routers/attachments.py`（挂 `main.py`，prefix `/api/chat/attachments`）
- `POST ""` 上传：每 turn 5 个限制（`count_nondeleted >= 5` → 422）→ 读内容
  （>25MB → 413）→ 校验（422）→ 存盘 `storage.L.attachments/{user}/{thread}/{uuid}`
  → 写 DB（status=uploaded，expires_at=now+7d）；写库失败回滚已落盘文件
- `GET ""?thread_id=` 列表（元数据，不含内容/storage_key）
- `DELETE /{id}` 所有权 404 → 物理删文件 + DB 删行（硬删，见决策）
- `GET /{id}/content` 下载（inline，所有权 404）——§34 未列但前端展示需要，按 brief
  「加则一并测试」实现
- `POST /{id}/save-to-knowledge` → 501（T3.3 接真实现）

### 4. 存储布局
`careercrew_api/storage.py` 的 `layout()` 增加 `attachments=up/"attachments"`；
docstring 同步。storage_key 存相对 attachments 根的相对路径（非绝对路径、非客户端
可控文件名——磁盘键名一律 UUID）。

### 5. 运行时接线
`careercrew_api/runtime.py`：`_ensure_heavy` 组装 `attachment_store =
AttachmentStore(create_attachment_db(settings))`；`tests/api/conftest.py` FakeRuntime
同步加 `attachment_store = AttachmentStore(FakeAttachmentDb())`。

### 6. TTL 清理脚本
`scripts/cleanup_chat_attachments.py`
- `cleanup_expired(store, attachments_root, now, dry_run)`：删 `expires_at < now` 且
  非 saved_to_knowledge 的附件（先物理删文件 → DB 删行）
- 磁盘路径由 storage_key + `resolve_under` 防目录穿越
- docstring 写明每日定时调度示例（Linux cron + Windows 任务计划程序）

## TDD 证据（RED → GREEN）

| 阶段 | RED 证据 | GREEN 结果 |
|---|---|---|
| 校验模块 | 导入 `careercrew_core.conversation.validation` ModuleNotFoundError | 22 passed |
| Store/DB | 导入 `assments` ModuleNotFoundError | 21 passed（含 6 个默认 TTL 新增）|
| 路由 | 上传命中 SPA fallback/404（router 未注册）| 10 passed |
| TTL 脚本 | 导入 `cleanup_chat_attachments` 失败 | 4 passed |
| PG 集成 | 缺 DSN 时 5 skipped | 设 `POSTGRES_TEST_DSN=.../careercrew_test` 后 5 passed |

修复轮记录（实现过程中发现并修正的真 bug）：
1. `dataclass(frozen=True)` 异常无法 set `__traceback__` → 改普通 Exception 类。
2. `.jpeg` + `image/jpeg` 被误拒 → 增加 `_extension_accepts_mime` JPEG 同族特例。
3. 路由挂载前缀错误（`/api/chat` → `405`）→ 改 `/api/chat/attachments`。
4. storage_key 相对 `DATA_ROOT`（越界）→ 改相对 `storage.L.attachments`。
5. **关键 bug**：磁盘文件名（router 生成 uuid4）与 DB id（store 生成 uuid7）不一致，
   导致下载/删除解析错路径（下载 404、删除不删文件）→ `AttachmentStore.create` 增加
   可选 `attachment_id` 参数，router 复用它保证 id == 文件名。
6. 测试 helper 混用 DB 级/Store 级参数 → 拆分 `_db_kwargs`/`_store_kwargs`。

## Magic 签名表（无第三方依赖）

| 扩展名 | 文件头签名（magic bytes） |
|---|---|
| `.pdf` | `%PDF-` |
| `.docx` | `PK\x03\x04`（ZIP）|
| `.pptx` | `PK\x03\x04`（ZIP）|
| `.xlsx` | `PK\x03\x04`（ZIP）|
| `.png` | `\x89PNG\r\n\x1a\n` |
| `.jpg` / `.jpeg` | `\xff\xd8\xff` |
| `.md` / `.txt` | 无签名 → 扩展名+MIME+UTF-8 可解码校验兜底 |

## 文件清单
新增：
- `careercrew_core/conversation/validation.py`
- `careercrew_core/conversation/attachments.py`
- `careercrew_api/routers/attachments.py`
- `scripts/cleanup_chat_attachments.py`
- `tests/unit/test_attachment_validation.py`
- `tests/unit/test_attachment_store.py`
- `tests/unit/test_attachment_ttl.py`
- `tests/api/test_attachments_api.py`
- `tests/integration/test_attachments_pg.py`

修改（仅本人 hunk，保留并行会话外来改动）：
- `careercrew_api/main.py`（只暂存 import 行 + include_router 行，外来异常处理器
  hunk 保持未暂存）
- `careercrew_api/runtime.py`
- `careercrew_api/storage.py`
- `tests/api/conftest.py`

## 决策（brief 允许实现者自定，已说明）
- 下载端点 `GET /{id}/content`：实现（§34 未列，前端展示需要，brief 明示「加则一并测试」）。
- DELETE 语义：硬删行 + 物理删文件（软 status=deleted 会残留无文件行，且 §34 列表已排除
  deleted，硬删最简，YAGNI）。
- 附件库与 conversation 同库（Postgres），store 独立文件 `attachments.py`（brief 建议路径）。

## 自审发现
- 存储路径安全：磁盘键名一律 UUID（router 生成），原文件名仅进元数据；下载/删除按 DB
  行的 user_id/thread_id 重新 resolve（不用客户端传来的 storage_key），`resolve_under`
  防目录穿越；`Path(file.filename).name` 剥路径穿越。✓
- 物理删除：DELETE 与 TTL 清理均 `unlink` 后再删行；TTL 只删「已过期且未保存知识库」。✓
- 每 turn 5 个限制在「校验前」计数（避免超限仍写盘）。✓
- 写库失败回滚已落盘文件，避免孤儿文件。✓
- 测试卫生：无外网/重组件依赖；PG 集成测试带一次性库 guard，缺 DSN 跳过。✓

## 疑虑 / 待办
1. `main.py` 的外来 hunk（全局异常处理器等）属并行会话，本提交只暂存了路由注册两行；
   并行会话提交 main.py 时需确保不冲突（已在报告说明）。
2. storage_key 相对 `attachments` 根（`u_001/t-1/{uuid}`）而非方案 §14.2 的完整
   `users/{user_id}/threads/{thread_id}/attachments/{uuid}`；brief 明示「storage_key 存
   相对路径字符串」，且磁盘实际布局已符合 `uploads/attachments/{user}/{thread}/{uuid}`。
3. save-to-knowledge 为 501 占位，T3.3 接真实现（届时 `mark_saved` + `clear_expires_at`
   已就绪）。
4. `count_nondeleted` 按 thread 未删除计数做每-turn 限制，但「turn」的严格定义（多轮
   上传是否累计 5 个）未在方案中明确；当前实现按 thread 级累计，符合 §14.1「5 文件/turn」
   的宽松解读，如需严格按 turn 隔离需 T3.2/T3.3 阶段再细化。

## Fix Round (review findings)

评审批准后修复三项 Important + 折叠的两个 cheap minor：

### 变更
1. **时钟/类型一致（Important 1）**：`careercrew_core/conversation/attachments.py`
   删除 `_now()`（str）与 `_now_dt()`（datetime）双 helper，统一为单一 `_now() ->
   datetime`（aware UTC）。`AttachmentDb` 契约的 `created_at`/`last_used_at`/
   `expires_at` 改为 `datetime | None`，`list_expired(now: datetime)`；`AttachmentStore
   .create` 直接 `_now() + timedelta(days=7)`，`expired_attachments` 直传 datetime；
   移除 `_iso`（不再对可能 naive 的 datetime 调 `.astimezone(utc)`）。Postgres 写入
   TIMESTAMPTZ 由 psycopg 对 datetime 对象原样落库；Fake 语义等价（`<` 比较 datetime）。
2. **UTF-8 全文校验（Important 2）**：`careercrew_core/conversation/validation.py`
   `validate_attachment` 新增关键字参数 `content: bytes | None`；文本类（md/txt）对
   **完整内容** `content`（缺省回退 `content_head`）做 `decode("utf-8")`，不再只看头
   64 字节；二进制签名校验仍只取头切片。路由层传入完整 `content`。
3. **有界分块读取（Important 3）**：`careercrew_api/routers/attachments.py` 新增
   `_read_bounded(file, limit)`：以 1MB 分块读入，累计超过 `MAX_ATTACHMENT_SIZE` 即
   返回 None（路由抛 413），不再 `await file.read()` 全量缓冲；保留 413 语义。
   `validate_attachment` 调用同步传 `content=content`。
4. **Minor（折叠）**：store 时间戳参数由 ISO 字符串改为 datetime 对象（并入修复 1）。

### 测试命令 + 结果
```
$ uv run pytest tests/unit/test_attachment_validation.py tests/unit/test_attachment_store.py tests/unit/test_attachment_ttl.py tests/api/test_attachments_api.py -q
# → 56 passed

$ $env:POSTGRES_TEST_DSN = uv run python -c "import re;raw=open('.env',encoding='utf-8').read();print(re.search(r'^DATABASE_URL=(.+)$',raw,re.M).group(1).strip().rsplit('/',1)[0]+'/careercrew_test')"
$ uv run pytest tests/integration/test_attachments_pg.py -q
# → 5 passed

$ uv run pytest -q   (with POSTGRES_TEST_DSN set)
# → 708 passed, 3 warnings
```

新增/更新测试：
- `tests/unit/test_attachment_validation.py`：`test_text_rejects_invalid_utf8_after_64_byte_head`
  （非法 UTF-8 出现在第 64 字节之后→拒绝）、`test_text_accepts_valid_utf8_full_body`。
- `tests/api/test_attachments_api.py`：`test_upload_bounded_read_no_full_buffer`（100MB
  假流，`_read_bounded` 返回 None 且单次读取 ≤1MB，断言未全量缓冲）。
- `tests/unit/test_attachment_store.py` / `test_attachment_ttl.py` /
  `tests/integration/test_attachments_pg.py`：`expires_at` 断言由 ISO 字符串改为
  datetime 对象（含 aware-UTC 断言）。

### 提交
### 提交
`4ba55ce` — `fix(attachments): single utc clock datetime params full utf8 validation bounded reads`
