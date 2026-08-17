# Task T0.1 Report — quality_reviewer 角色（Phase 0）

## What I implemented

Phase 0 角色基础设施：`quality_reviewer` 角色的值、存储/校验/分配/依赖/迁移。按 brief 精确验收标准逐条落实，未构建任何 Quality 端点（Phase 5）。

1. **`careercrew_api/auth/store.py`**
   - `_ROLES` 从 `("admin", "user")` 扩为 `("admin", "user", "quality_reviewer")`。
   - 内联 `CREATE TABLE IF NOT EXISTS` 的 role CHECK 增加 `'quality_reviewer'`（新库直接正确）。
   - 新增**幂等迁移**：`ALTER TABLE auth_accounts DROP CONSTRAINT IF EXISTS auth_accounts_role_check` + `ADD CONSTRAINT auth_accounts_role_check CHECK (role IN (...))`，在 `PostgresAccountStore.__init__` 内、事务中执行，解决已有库旧 CHECK 不随 CREATE TABLE IF NOT EXISTS 更新的问题。任何既有数据（admin/user）仍满足新约束，无数据丢失。
   - `update_account` 的 `_ROLES` 校验自动放开新角色。

2. **`careercrew_api/auth/dependencies.py`**
   - 新增 `require_quality_reviewer`：`user["role"] == "quality_reviewer"`，否则 403 `"quality reviewer required"`。admin **不**自动满足（依赖本身只认 reviewer）。
   - 暴露 `QualityReviewer: TypeAlias`。

3. **`careercrew_api/schemas.py`**
   - 三处 `Literal["user", "admin"]` 放开为 `Literal["user", "admin", "quality_reviewer"]`：`CreateUserRequest.role`、`PublicUser.role`、`AccountListItem.role`、`UserPatchRequest.role`。

4. **`tests/fakes.py`**
   - `FakeAccountStore` 增加角色/状态校验（`_VALID_ROLES`/`_VALID_STATUSES`），使测试替身与 `PostgresAccountStore` 语义对齐（此前 fake 不校验角色，导致"非法角色拒绝"无法在单元层验证）。

5. **测试**（详见下节）
   - 新增 `tests/unit/test_quality_reviewer_role.py`、`tests/unit/test_quality_reviewer_dependency.py`。
   - 扩展 `tests/api/test_auth_api.py`、`tests/integration/test_postgres_account_store.py`。

## What I tested and results

- 聚焦测试（全部 GREEN）：`tests/unit/test_quality_reviewer_role.py`、`tests/unit/test_quality_reviewer_dependency.py`、`tests/api/test_auth_api.py::test_admin_assigns_quality_reviewer_and_dependency_gates`、`tests/unit/test_auth_service_guards.py` —— 30 项相关测试全部通过。
- 完整后端套件：`uv run pytest` → **439 passed, 8 skipped, 0 failed**（无新增失败；StarletteDeprecationWarning 为既有告警，非本任务引入）。
- 迁移验证：对真实 dev 库 `localhost:5432/careercrew`（旧约束库）执行 `PostgresAccountStore` 两次初始化，确认旧 CHECK 已升级为含 `quality_reviewer`，且重复执行无报错（幂等）。
- 集成测试 `tests/integration/test_postgres_account_store.py`（含新增 2 项）因未设 `POSTGRES_TEST_DSN` 跳过，符合既有 guard 模式（拒绝指向生产库）。

## TDD Evidence

### RED

命令：
```
uv run pytest tests/unit/test_quality_reviewer_dependency.py -q
```

失败输出摘录：
```
ImportError: cannot import name 'require_quality_reviewer' from 'careercrew_api.auth.dependencies'
```

为何预期失败：依赖 `require_quality_reviewer` 尚不存在，说明 RED 状态正确（实现缺失）。

另：`test_store_rejects_unknown_role` 初始 RED 暴露了 `FakeAccountStore` 不校验角色的问题（`KeyError` 而非 `ValueError`），据此修正 fake 与实现语义对齐。

### GREEN

命令：
```
uv run pytest tests/unit/test_quality_reviewer_role.py tests/unit/test_quality_reviewer_dependency.py tests/api/test_auth_api.py::test_admin_assigns_quality_reviewer_and_dependency_gates tests/unit/test_auth_service_guards.py -q
```

输出：
```
...............                                                          [100%]
```

全绿。完整套件：`439 passed, 8 skipped`。

## Files changed

- `careercrew_api/auth/store.py`
- `careercrew_api/auth/dependencies.py`
- `careercrew_api/schemas.py`
- `tests/fakes.py`
- `tests/api/test_auth_api.py`
- `tests/integration/test_postgres_account_store.py`
- `tests/unit/test_quality_reviewer_role.py`（新）
- `tests/unit/test_quality_reviewer_dependency.py`（新）

## Self-review findings

- **完整性**：brief 六条验收标准全部覆盖：
  1. ✅ 合法角色（DB CHECK / `_ROLES` / API Literal）接受，其余拒绝（store ValueError + DB CHECK；API 422）。
  2. ✅ admin 可互转 user ↔ quality_reviewer，写审计（`_audit` 经 `update_user` 不变）并递增 token_version。
  3. ✅ `require_quality_reviewer` 存在；reviewer 访问 require_admin → 403；user 访问 reviewer 依赖 → 403（直接以依赖函数验证）。
  4. ✅ last-admin 回归：reviewer 不计入 active admin 数；唯一 admin 降级仍抛 `LastAdminError`。
  5. ✅ 幂等迁移：对真实旧约束库验证成功且重复执行无错。
  6. ✅ JWT role claim 无需改动：reviewer 登录 token role claim == `'quality_reviewer'`，`current_user` 校验通过。
- **YAGNI/纪律**：只交付角色基础设施，未建 Quality 端点；未动前端。
- **测试质量**：测试验证真实行为（角色写入/读出、权限依赖、last-admin 语义、迁移幂等），非纯 mock。对外部依赖（Postgres）用既有 fake + 集成测试 guard 模式。
- **Pristine 输出**：无本任务引入的告警（既有 `StarletteDeprecationWarning` / `UserWarning` 为基线固有）。

## Issues / Concerns

1. **前端 role 展示**：`AdminUsersPage.tsx` / `CreateUserDialog.tsx` 硬编码 `"admin" | "user"` 联合类型与 `ROLE_LABEL`（管理员/普通用户），无 `quality_reviewer` 选项。按 brief「大概率无需动前端」「仅当 UI 有下拉枚举时最小同步」及 Phase 0 边界，本次未改动。若 Phase 5 需要在管理界面分配 reviewer，需同步放开前端 role 枚举与标签（`ROLE_LABEL["quality_reviewer"]` 当前会渲染空标签）。
2. **集成测试依赖 `POSTGRES_TEST_DSN`**：新增的 2 项迁移/校验集成测试在当前环境因未设 `POSTGRES_TEST_DSN` 跳过（与既有 3 项一致）；需在提供一次性测试库的 CI 中才能实际执行 DB CHECK 迁移断言。已通过直连真实 dev 库单独验证迁移幂等（只读验证，未改动数据语义）。
3. **`_ROLES` 单一来源**：`FakeAccountStore` 中的 `_VALID_ROLES` 与 `store._ROLES` 目前重复维护（fake 独立定义），未来若再增角色需两处同步。可考虑 fake 直接 `from careercrew_api.auth.store import _ROLES`，但 `_ROLES` 是私有名；本次为最小改动保持独立常量。

## Fix Round (review findings)

评审接受任务但提出两项 Important 意见，均已修复（commit `f0c6f1f`）。

### 修改内容

1. **Finding 1 — `careercrew_api/auth/store.py` 迁移事务化**：`PostgresAccountStore.__init__` 中幂等 role-CHECK 迁移（`DROP CONSTRAINT IF EXISTS auth_accounts_role_check` + `ADD CONSTRAINT ... CHECK (role IN ('admin','user','quality_reviewer'))`）原本未包装事务。现以 `with conn.transaction():` 包裹两条 `ALTER` 语句，与文件其余写方法的方式保持一致；仍幂等，约束名与新 CHECK 不变。

2. **Finding 2 — `tests/fakes.py` 常量去重**：将 `store.py` 的私有常量提升为公开 `ROLES`/`STATUSES`，并保留 `_ROLES`/`_STATUSES` 兼容别名（无其他代码依赖这些私有名）。`fakes.py` 删除自身重复的 `_VALID_ROLES`/`_VALID_STATUSES`，改为 `from careercrew_api.auth.store import ROLES, STATUSES` 并在 `create_account`/`update_account` 中引用。此后新增角色只需改生产常量一处。

### 测试命令与结果

- 覆盖测试：
  ```
  uv run pytest tests/unit/test_quality_reviewer_dependency.py tests/unit/test_quality_reviewer_role.py tests/api/test_auth_api.py -q
  ```
  → **19 passed**（原 brief 提及的 `test_auth_store.py` 实际不存在，覆盖 store 的单元测试为 `test_quality_reviewer_role.py`）。

- 完整后端套件：
  ```
  uv run pytest
  ```
  → **439 passed, 8 skipped, 3 warnings**（与基线 439 passed 一致，无失败）。

### Commit

`f0c6f1fd74a82f890bf4a8839dfe6cba83233b69` — `fix(auth): wrap role migration in explicit transaction and dedupe role constants`
