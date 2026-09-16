# CareerCrew 发布验收门禁

`scripts/release_acceptance.py` 是发布前的统一验收入口。它把迁移 schema、Qdrant 健康与 owner dry-run、备份 artifact、备份介质证据、重索引证据、隔离恢复演练和受保护真实模型评测放进同一份脱敏 JSON 报告。

## 目标边界

- `--target local` 只产生 `rehearsal_passed`，代表本地 Docker 演练，不代表生产通过。
- `--target production` 必须同时设置 `CAREERCREW_RELEASE_TARGET=production`；源 PostgreSQL/Qdrant 不得是回环地址。
- 恢复演练必须使用独立 PostgreSQL 和独立 Qdrant 端点，并设置 `CAREERCREW_RELEASE_RESTORE_DRILL=1`；生产还必须提供不同的 `CAREERCREW_RELEASE_SOURCE_RESOURCE_ID` / `CAREERCREW_RELEASE_RESTORE_RESOURCE_ID` 资源身份 attestation。脚本不会用生产源端点创建临时数据库或恢复集合。
- 迁移检查是只读的：先由部署流程执行 `alembic upgrade head`，再运行本门禁确认真实 head 和 schema invariant。
- 真实模型评测只接受 `--real --runtime --require-real --fail-on-regression` 的 `completed` 报告；缺少凭据、依赖、case 观测或回归时失败，不允许 `--allow-skip`。
- production 的备份介质和重索引 JSON 不是事实来源；每项还必须由受保护的外部 evidence verifier 返回匹配的服务端回执。

## 生产运行

真实凭据通过受保护的 secret/environment 注入，不要把带密码的 DSN 放进命令行。`--database-url` 为兼容参数，生产优先使用 `DATABASE_URL` 环境变量。

```powershell
$env:CAREERCREW_RELEASE_TARGET = "production"
$env:CAREERCREW_RELEASE_RESTORE_DRILL = "1"
$env:DATABASE_URL = "postgresql://<user>:<password>@<production-host>:5432/careercrew"
$env:QDRANT_URL = "https://<production-qdrant-host>"
$env:CAREERCREW_RELEASE_SOURCE_RESOURCE_ID = "prod/qdrant-cluster-a"
$env:CAREERCREW_RELEASE_RESTORE_RESOURCE_ID = "restore/qdrant-cluster-b"
$env:RESTORE_DATABASE_URL = "postgresql://<restore-user>:<password>@<isolated-restore-host>:5432/restore_control"
$env:RESTORE_QDRANT_URL = "https://<isolated-restore-qdrant-host>"
$env:RESTORE_QDRANT_API_KEY = "<isolated-restore-qdrant-key>"
# 仅使用 Docker 中的 Qdrant 时才需要；托管 Qdrant 走 snapshot upload API，不需要容器名
# $env:RESTORE_QDRANT_CONTAINER = "<isolated-restore-qdrant-container>"
$env:CAREERCREW_EVAL_RUNTIME = "1"
$env:CAREERCREW_EVAL_RUN_ID = "release_20260911"
$env:CAREERCREW_EVAL_USER_ID = "eval_release_20260911"
$env:CAREERCREW_EVAL_TENANT_ATTESTATION = "eval_release_20260911:release_20260911:provisioned"
$env:CAREERCREW_EVAL_TENANT_ATTESTATION_URL = "https://<protected-provisioner>/v1/eval-tenants/attest"
$env:CAREERCREW_EVAL_TENANT_ATTESTATION_TOKEN = "<protected-provisioner-token>"
$env:CAREERCREW_EVAL_TENANT_ATTESTATION_NONCE = "<provisioning-issued-unique-nonce>"
$env:CAREERCREW_RELEASE_EVIDENCE_VERIFIER_URL = "https://<protected-release-verifier>/v1/verify"
$env:CAREERCREW_RELEASE_EVIDENCE_VERIFIER_TOKEN = "<protected-release-verifier-token>"
$env:CAREERCREW_EVAL_DISABLE_REMOTE_TRACING = "1"

F:\Python_develop\miniconda3\envs\careercrew\python.exe scripts/release_acceptance.py `
  --target production `
  --backup-dir <verified-backup-run> `
  --backup-media-evidence <backup-media-evidence.json> `
  --reindex-evidence <reindex-evidence.json> `
  --run-real-eval `
  --report <release-acceptance.json>
```

退出码为 `0` 才表示 `accepted`。`1` 表示某个验收项失败或未执行，`2` 表示目标/配置边界拒绝。生产模式不读取仓库 `.env`，拒绝通过命令行传入 PostgreSQL DSN 或 Qdrant 地址；报告只保留检查名、状态、计数和脱敏细节，不上传或记录 DSN、token、prompt、回答和原始 PII。

仓库 CI 的 `workflow_dispatch` 提供 `run_production_acceptance` 受保护入口。`release` environment 需要配置 `CAREERCREW_RELEASE_DATABASE_URL`、`CAREERCREW_RELEASE_QDRANT_URL`、`CAREERCREW_RELEASE_RESTORE_DATABASE_URL`、`CAREERCREW_RELEASE_RESTORE_QDRANT_URL` 及对应 API/JWT secrets；还需要配置不同的 `CAREERCREW_RELEASE_SOURCE_RESOURCE_ID`、`CAREERCREW_RELEASE_RESTORE_RESOURCE_ID` 和唯一的 `CAREERCREW_RELEASE_EVAL_RUN_ID` variables。另需配置租户 provisioning URL/token/nonce 和 evidence verifier URL/token；缺少任一项时受保护门禁失败。`CAREERCREW_RELEASE_BACKUP_DIR`、`CAREERCREW_RELEASE_BACKUP_MEDIA_EVIDENCE`、`CAREERCREW_RELEASE_REINDEX_EVIDENCE` 和模型路径使用 environment variables。若备份目录位于受控主机，应将 `CAREERCREW_RELEASE_RUNNER` 指向已挂载该目录和模型缓存的 self-hosted runner；job 会先检查路径和凭据，再执行完整生产门禁并上传脱敏报告。

## 受保护真实模型评测

`scripts/eval_runner.py --real --runtime` 会调用真实 `CareerCrewRuntime`：路由走会诊调度节点，知识库/引用走真实 embedding + Qdrant + `knowledge_advisor`，工具 case 走 `job_matcher`，会诊 case 走真实 fan-out graph。它不把模型直接提示成 JSON 来替代产品运行链路。

运行前必须在受保护环境中按唯一 run id 准备专用 `eval_<run-id>` 租户，并由租户 provisioning 流程提供匹配的 `CAREERCREW_EVAL_TENANT_ATTESTATION`。真正执行前，runner 还会向 `CAREERCREW_EVAL_TENANT_ATTESTATION_URL` 提交 user/run/nonce，并要求服务端回执同时匹配租户、nonce 和未来的 `expires_at`；本地字符串不能单独证明租户已 provision。还要预置固定评测集所需的知识文档和记忆事实。评测会为每个 case 生成 UUID 会话，结束后清理该专用租户的会话、记忆镜像、记忆 trace/outbox 和情景向量，不调用普通账号级清空；最终数据库 sweep、向量残留检查或会话残留检查失败都会使评测失败。若记忆治理审计事件已存在，审计链按 append-only 规则保留，记录改为 `deleted`。受保护 runtime 默认关闭远程 LangSmith trace，除非另有外部 trace retention/delete 证据。以下变量属于门禁契约：

```text
CAREERCREW_EVAL_RUNTIME=1
CAREERCREW_EVAL_USER_ID=eval_<dedicated-tenant>
CAREERCREW_EVAL_RUN_ID=<unique-run-id>
CAREERCREW_EVAL_TENANT_ATTESTATION=eval_<unique-run-id>:<unique-run-id>:provisioned
CAREERCREW_EVAL_TENANT_ATTESTATION_URL=https://<protected-provisioner>/v1/eval-tenants/attest
CAREERCREW_EVAL_TENANT_ATTESTATION_TOKEN=<protected-provisioner-token>
CAREERCREW_EVAL_TENANT_ATTESTATION_NONCE=<provisioning-issued-unique-nonce>
CAREERCREW_EVAL_DISABLE_REMOTE_TRACING=1
DATABASE_URL=<protected runtime database>
QDRANT_URL=<protected runtime qdrant>
QDRANT_API_KEY=<optional protected qdrant key>
CAREERCREW_ENV=production
AUTH_JWT_SECRET=<protected runtime JWT secret>
CAREERCREW_EMBEDDING_MODEL_PATH=<runtime BGE-M3 directory>
```

仓库提供的 GitHub Actions `release` 环境会在执行前检查这些受保护变量；尤其是
`CAREERCREW_EMBEDDING_MODEL_PATH` 必须指向评测 runner 上已经缓存的 BGE-M3 目录。
缺少任一前置值时 job 失败，不会退回本机路径或直接模型探针。

`--model-probe` 仅保留给供应商连通性诊断；它不能与 `--require-real` 一起使用。缺少 runtime 标记、专用租户、模型依赖、真实 case 观测或清理证据时，评测失败或在显式 `--allow-skip` 的 nightly 任务中标记为 skipped，不会变成通过。

## 必须提供的外部证据

备份目录必须是 `scripts/backup_restore.py create` 生成的完整 run，当前格式为 `careercrew-backup-v2`；`manifest.json` 中的 PostgreSQL dump、上传/解析文件 ZIP、Qdrant snapshots 均能通过 SHA-256/size/ZIP 校验，上传/解析 ZIP 内每个文件还必须有独立的 size/SHA-256 清单。备份介质证据 JSON 至少包含：

```json
{
  "status": "verified",
  "target": "production",
  "verified_at": "2026-09-11T01:00:00Z",
  "artifact_count": 3,
  "media_uri": "s3://release/backup/20260911",
  "manifest_sha256": "<sha256-of-manifest>",
  "remote_manifest_sha256": "<sha256-of-uploaded-manifest>",
  "verification_id": "media-check-20260911",
  "provider": "s3",
  "provider_verified": true,
  "remote_exists": true,
  "provider_verification_id": "provider-cli-check-20260911",
  "retention_days": 30,
  "immutable_until": "2026-10-11T01:00:00Z",
  "encrypted": true,
  "offsite": true,
  "immutable": true
}
```

production 还必须把该 JSON 的 SHA-256 和 manifest 摘要提交给
`CAREERCREW_RELEASE_EVIDENCE_VERIFIER_URL`。服务端回执必须包含
`status=verified`、匹配的 `kind=backup_media`、`evidence_sha256`、
`manifest_sha256`、源/恢复资源身份，以及 `remote_exists=true`、
`immutable=true`。本地 JSON 中的 `provider_verified` 等布尔值不会替代该回执。

重索引证据 JSON 必须绑定 production，并证明 shadow collection、owner/失败计数、查询 canary、cutover 和临时资源清理均成功：

```json
{
  "status": "completed",
  "target": "production",
  "started_at": "2026-09-11T00:00:00Z",
  "completed_at": "2026-09-11T00:20:00Z",
  "verified_at": "2026-09-11T00:21:00Z",
  "cutover_at": "2026-09-11T00:20:30Z",
  "cleanup_at": "2026-09-11T00:21:00Z",
  "documents": 2,
  "versions": 2,
  "chunks": 18,
  "failed": 0,
  "owner_conflicts": 0,
  "source_collection": "careercrew_mm",
  "shadow_collection": "careercrew_mm__release_20260911",
  "canary_queries": 3,
  "cutover": "completed",
  "canary_passed": true,
  "cleanup_passed": true
}
```

production 重索引证据同样必须取得外部回执。回执要匹配该 JSON 的
`evidence_sha256`、`kind=reindex`，并确认 `cutover=completed`、
`canary_passed=true`、`cleanup_passed=true` 及源/恢复资源身份；只在本地
文件中填写这些字段不能通过门禁。

这些 JSON 只是验收证据契约，不会把本地合成演练自动升级为生产证据。若没有真实 production target、独立恢复目标、介质证明、重索引证明或受保护模型凭据，报告必须保持失败/未执行状态。

## 本地自检

### 2026-09-16 门禁口径补充

- `verify_qdrant_ownership.py` 的 dry-run 现在是严格只读：不会创建快照，也不会写入
  payload；只有 `--apply` 才会先建快照再回填。release acceptance 仍只允许 dry-run。
- ownership 报告必须覆盖 `--target` 要求的全部必需集合，缺失任何一个都会拒绝通过，
  避免"辅助集合干净、必需集合未检查"的假通过。
- `backup_restore.parse_database_url` 会拒绝继承的 libpq 路由变量
  （`PGHOST`/`PGHOSTADDR`/`PGPORT`/`PGDATABASE`/`PGSERVICE`/`PGSERVICEFILE`/
  `PGOPTIONS`），防止"回执写 A 主机、实际连 B 主机"。
- 受保护真实模型评测在 runtime 准备阶段就会解析实际设置并与回执中的部署身份比对；
  当前 runtime 还没有独占写入租约，无法证明清理后不会有在途 worker 重新写入，
  因此 live 评测保持 fail-closed（返回 `isolation` 类别错误），不会以"跳过"计为通过。
- ownership dry-run 的 `conflicts` 统计的是"主键已存在但与默认 owner 不一致"的点。
  本地开发库中存在 4 条属于已删除账号的遗留向量，门禁因此保持失败；这是数据治理
  决策（清理或改判归属），不是代码缺陷。

### 外部回执的部署绑定

租户评测回执必须匹配请求中的 `deployment`；生产介质与重索引回执必须匹配
`deployments.source` 和 `deployments.restore`。每个部署包含无凭据的数据库
`host`、`port`、`database` 以及规范化的 Qdrant URL。数据库路由覆盖参数会被拒绝。
外部验证服务必须独立核实这些端点对应其管理的资源 ID，不能直接回显请求即表示通过。
这只是客户端门禁协议；未部署可信验证服务、未获得真实回执时，不构成生产验收。

本地只用于检查编排逻辑和当前 Docker 服务。完整恢复演练还需要一个已经生成的 backup run，并显式设置 `CAREERCREW_RELEASE_RESTORE_DRILL=1`：

```powershell
$env:CAREERCREW_RELEASE_RESTORE_DRILL = "1"
$env:RESTORE_DATABASE_URL = "postgresql://<user>:<password>@localhost:5434/restore_control"
$env:RESTORE_QDRANT_URL = "http://127.0.0.1:7333"
F:\Python_develop\miniconda3\envs\careercrew\python.exe scripts/release_acceptance.py `
  --target local `
  --backup-dir data/backups/careercrew-YYYYMMDD-HHMMSS `
  --report data/reports/local-release-acceptance.json
```

`scripts/backup_restore.py restore-drill` 支持两种 Qdrant 恢复方式：提供 `--qdrant-container` 时使用 Docker 文件恢复；不提供容器名时向显式传入的恢复 Qdrant URL 的临时集合上传 snapshot，因此生产演练可以使用隔离的托管 Qdrant。恢复验收还会在临时目录逐个校验上传/解析文件的 manifest、在恢复数据库执行代表性表计数和跨表孤儿关系 canary，并在清理前把结果写入返回证据；任何文件漂移、schema/关系错误或 canary 失败都会阻断演练。恢复验收必须使用 `RESTORE_QDRANT_URL`，并为该目标提供 `RESTORE_QDRANT_API_KEY`（如目标启用认证）；源端点、源端容器和源端密钥都不会回退到恢复目标。

`docs/OPS_RELEASE_REHEARSAL.md` 记录的是隔离合成发布演练；本文件记录的是统一门禁和生产所需的真实外部证据，两者不能互相替代。
