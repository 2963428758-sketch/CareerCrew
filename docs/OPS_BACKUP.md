# CareerCrew 备份与恢复手册

## 1. 组件与位置

| 组件 | 位置 | 备份方式 |
|---|---|---|
| 账号/刷新会话/审计/限速 | Postgres `auth_accounts` / `auth_refresh_sessions` / `admin_audit_events` / `auth_login_attempts` | `pg_dump` |
| 会话/记忆/画像/线程 | Postgres（`DATABASE_URL` 指向库）其余表 | `pg_dump` |
| 知识库向量 `careercrew_mm` / 情景记忆 `careercrew_episodic_v2` | Qdrant（`http://localhost:6333`） | collection snapshot |
| 上传原件/解析产物/简历 | `data/`（uploads/parsed） | 文件复制/压缩 |

## 2. 备份命令（Windows PowerShell）

```powershell
# Postgres（含账号与记忆）
$env:PGPASSWORD="careercrew"
pg_dump -h localhost -U careercrew -d careercrew -Fc -f "backup\careercrew_$((Get-Date -Format yyyyMMdd-HHmmss)).dump"

# Qdrant snapshot
Invoke-RestMethod -Uri http://localhost:6333/collections/careercrew_mm/snapshots -Method Post | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:6333/collections/careercrew_episodic_v2/snapshots -Method Post | ConvertTo-Json
# snapshot 文件默认在 Qdrant 数据目录 snapshots/ 子目录，恢复前将其拷贝备份

# 文件
Compress-Archive -Path data\uploads,data\parsed -DestinationPath "backup\data_$((Get-Date -Format yyyyMMdd-HHmmss)).zip"
```

## 3. 恢复

1. 停应用 → `pg_restore -h localhost -U careercrew -d careercrew --clean backup\careercrew_xxx.dump`
2. Qdrant：新建同名 collection 后 `POST /collections/{name}/snapshots/recover`（body: `{"location": "<snapshot文件URL或路径>"}`），或把 snapshot 文件放回 snapshots 目录用控制台恢复。
3. 解压 `data` zip 到仓库根（保持 uploads/parsed 目录结构）。
4. 启动应用；管理员登录确认用户数与知识库点数与备份时一致。

## 4. 例行事项

- 过期刷新会话由应用内置清理任务自动删除（周期 `auth.cleanup_interval_hours`）。
- 账号迁移：SQLite 仅测试用；运行时以 `auth.backend=postgres` + `AUTH_DATABASE_URL`（回退 `DATABASE_URL`）为准。
- 迁移类脚本均有 dry-run 默认值：`scripts/migrate_accounts_postgres.py`、`scripts/migrate_knowledge_visibility.py`、`scripts/migrate_legacy_tenant.py`、`scripts/migrate_uploads.py`。
- **集成测试红线**：`POSTGRES_TEST_DSN` 只允许指向一次性测试库（推荐 `careercrew_test`），禁止指向生产库 `careercrew`——测试内置护栏（指向 careercrew 直接拒绝运行），违例会清空账号表。
