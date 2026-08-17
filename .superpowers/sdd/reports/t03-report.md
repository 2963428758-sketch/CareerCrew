# T0.3 报告 — 跨用户隔离测试矩阵基线

## 实现内容

1. **可复用双/三账号 fixture**：在 `tests/api/conftest.py` 新增 `build_tenant_client(...)`
   与 `tenant_api` fixture，把原本散落在 `test_tenant_isolation_api.py` /
   `test_upload_isolation_api.py` / `test_thread_scope_api.py` 三处重复的"双用户"构建
   模式收敛为一处。产出：
   - `alice`（admin，兼作"用户 A"）
   - `bob`（user，"用户 B"）
   - `carol`（quality_reviewer，API 级边界断言用）
   每账号拿到真实 JWT access token，并完成强制改密，使业务 API 放行；Runtime 用
   FakeRuntime 注入（不触发重组件初始化），鉴权层（AuthService + FakeAccountStore）真实。

2. **隔离矩阵测试**：新建 `tests/api/test_cross_user_isolation.py`（12 条 web 测试），
   覆盖方案 §41 本 Phase 可覆盖的每一行：

   | §41 断言 | 测试 |
   | --- | --- |
   | A 无法 GET B Thread | `test_thread_list_hides_other_users_threads` |
   | A 无法 PATCH B Thread（拒绝且不生效） | `test_thread_patch_cross_user_rejected_and_not_effective` |
   | A 无法 DELETE B Thread（拒绝；A 自己的不受影响） | `test_thread_delete_cross_user_rejected_and_owner_intact` |
   | A 无法 list B Memory | `test_memory_list_cannot_read_other_users_thread` |
   | A 无法 delete B Memory | `test_memory_delete_cannot_delete_other_users_memory` |
   | B 无法 GET A 的 private 文档 | `test_knowledge_private_doc_hidden_from_other_user` |
   | B 无法删除 A 的 private 文档 | `test_knowledge_cannot_delete_others_private_doc` |
   | B 无法在 ask 引用 A 的 private 文档 | `test_knowledge_ask_cannot_reference_others_private_doc` |
   | B 可访问 A 的 public 文档（隔离≠全禁） | `test_knowledge_public_doc_accessible_to_other_user` |
   | 伪造 visibility（上传 public / 非法值） | `test_cannot_forge_visibility_on_upload` |
   | 伪造 visibility（改他人文档可见性） | `test_cannot_change_others_doc_visibility` |
   | Reviewer 无法调用 `/api/auth/users*`（403） | `test_quality_reviewer_cannot_manage_accounts` |

3. **未覆盖清单**：写入 `.superpowers/sdd/briefs/t03-deferred.md`（纯记录，不进 git）。

## TDD 证据

本任务目标是"复用既有正确实现钉住隔离语义"，测试在首次运行即 **GREEN**——说明当前
所有权校验（runtime.py + data.py + knowledge.py 中按 `user_id`/`owner_user_id`/`__access_user`
过滤）语义已经正确，未暴露越权漏洞。TDD 的 RED 阶段在此表现为：若实现有洞，以下针状
断言（PATCH/DELETE 返回 404、private 文档不可见、public 仅 admin 可发布）会失败；实测
全部通过。

- **RED**：无独立 RED 记录——12 条断言在既有实现上直接通过，未发现需要修复的越权洞。
- **GREEN**（聚焦）：
  ```
  $ uv run pytest tests/api/test_cross_user_isolation.py -q
  12 passed, 1 warning in 23.78s
  ```
- **GREEN**（全量）：
  ```
  $ uv run pytest -q   # exit code 0
  471 tests collected  (基线 459 = 451 passed + 8 skipped；+12 新增)
  ```

## 越权漏洞清单

**无**。线程/记忆/知识库/可见性的跨用户隔离在既有实现中已正确。没有 `fix(api:)` 提交。

## 改动文件

- `tests/api/conftest.py`（+103 行：`build_tenant_client` + `tenant_api` fixture）
- `tests/api/test_cross_user_isolation.py`（+249 行，新建 12 条测试）

提交：`8c632fd` `test(api): cross-user isolation matrix for threads, memory, knowledge`

## 自审发现

1. **fixture 收敛但未强制迁移旧文件**：既有三份重复的 `tenant_api` fixture 未改动（避免
   触碰已有绿测试、降低回归风险）。这些旧文件未来可逐步改为引用 `build_tenant_client`。
2. **`tenant_api` fixture 命名与既有测试文件内的局部 fixture 同名**：新 fixture 定义在
   `tests/api/conftest.py`，与 `test_tenant_isolation_api.py` 等文件内的**模块级**同名
   fixture 不冲突（模块级 fixture 覆盖 conftest 级）。新 fixture 仅供本矩阵文件使用。
3. **`.superpowers` 不在 gitignore**：简报称"gitignore 已覆盖 .superpowers/sdd/briefs/"，
   但实测 `git check-ignore` 对所有 `.superpowers/**` 返回未忽略（exit 1）。已通过
   "仅精确 stage test 文件"规避，未误提交任何 .superpowers 工件；建议后续补齐 gitignore。
4. **公共库可见性断言的粒度**：`test_knowledge_ask_cannot_reference_others_private_doc`
   通过 FakeRuntime 的 `knowledge_output_by_user` 与 `knowledge_ask_scopes` 验证 scope
   透传，但真正的"私有文档不被检索到"由 `_knowledge_scope_filters`（runtime 层）保证，
   该函数的单测在 `tests/unit/test_verify_qdrant_ownership.py` / 相关单测覆盖；API 层
   只能验证到 scope 路由与输出归属，属预期内的分层边界。
5. **未触碰生产代码**：满足"除测试外不引入新功能"纪律。

## 顾虑

- 简报中"dry-run 0 changed / 0 conflict"（§45）针对数据库迁移，本任务不涉及迁移，未运行。
- Reviewer 的 403 断言与 T0.1 已有测试（`test_auth_api.py::test_admin_assigns_quality_reviewer_and_dependency_gates`）
  有轻微重叠，但本任务按简报要求补了 API 级、三端点的独立断言。

## Fix Round (review findings)

针对 reviewer 两条 Important 意见的修复。

**Finding 1 — `tests/api/test_cross_user_isolation.py::test_memory_delete_cannot_delete_other_users_memory`**
原断言只校验 200 + "list 仍非空"，未校验 `removed == 0`。修复：
- 删除前抓取 Alice 的 memory 完整快照；
- 断言 `resp.json()["removed"] == 0` 与 `resp.json()["deleted"] == 0`（端点 body 为
  `{"deleted": removed, "removed": removed}`，见 routers/data.py:182）；
- 删除后断言 `after == before`（逐字段相等），不再是仅"非空"。

**Finding 2 — 知识库所有权测试只覆盖 FakeRuntime，未覆盖生产 store**
新增强测试 `tests/unit/test_knowledge_ownership_store.py`（Finding 2 修复）：
- 用**真实** `QdrantStore`（`:memory:` 本地模式，与 test_ingestion_pipeline.py 一致）
  播种用户 A/B 的 private + A 的 public 文档；
- 直接调用生产 `CareerCrewRuntime` 的 `_knowledge_scope_filters` / `knowledge_status` /
  `delete_document`（以 `_initialized=True` + 真实 store 的轻量实例规避重组件，不 mock 过滤逻辑）。
- 钉住的 seam：`owner_user_id` 键名错配或 `__access_user` 的 should-表达式（public OR own）
  序列化回归会在此失败。`_knowledge_scope_filters` 三档 scope 的返回键/值有一组 parametrized
  逐字段断言。
- 未弱化/移除任何既有 FakeRuntime 测试，全部保留。

**测试命令与结果**：
```
$ uv run pytest tests/api/test_cross_user_isolation.py tests/unit/test_knowledge_ownership_store.py -q
19 passed, 3 warnings in ~25s
$ uv run pytest   # exit code 0
470 passed, 8 skipped, 3 warnings in 133.41s   (478 collected)
```

**提交**：`e24bd08` `test(api): assert memory delete no-op and cover real knowledge store ownership`
