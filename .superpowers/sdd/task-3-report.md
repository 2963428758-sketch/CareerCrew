# Task 3 实施报告：认证主体驱动的完整租户隔离

## 结论

本任务已完成。业务 API 的用户身份统一来自认证主体；线程、运行时缓存、情景记忆、简历、知识库、向量记录、图片资产和 checkpoint 内部配置均按认证用户隔离。外部请求中遗留的 `user_id` 字段由 Pydantic 忽略，不能选择其他租户。新增双用户 API/集成回归和一个默认 dry-run、显式 apply、可重复运行的旧数据迁移脚本。

## 实施内容

### 1. 认证主体成为唯一身份来源

- 在 `careercrew_api/auth/dependencies.py` 增加 `CurrentUser` / `AdminUser` 依赖别名，统一业务路由的认证注入。
- 从业务请求模型中移除公开的 `user_id` 字段；兼容旧客户端的额外字段会被忽略，但不会参与授权或数据选择。
- chat、consult、interview、resume、knowledge、profile/thread/memory 等业务端点全部从 `current_user["id"]` 取得用户身份。
- 全局 memory settings 修改限制为管理员；资源不存在和跨用户访问均返回相同的 404，不暴露资源是否属于其他用户。

### 2. 线程、记忆与运行时隔离

- `ThreadStore` 的所有读取、创建、更新、删除操作改为显式 `(user_id, thread_id)`。
- runtime `_cycles` 缓存键改为 `(user_id, thread_id)`，允许两个用户使用相同公开 thread ID 而不共享 `JobCycle`。
- 所有 match/resume/plan/interview/consult/knowledge 调用链显式传递认证用户对应的 episodic memory，不再以 `u_001` 作为请求期默认值。
- MemoryInjector 的数据库回退也按调用用户查询，避免旧的固定用户情景记忆泄漏。
- 线程删除、修改前执行租户范围内查询；其他租户的同名线程不可读取或变更。

### 3. Qdrant、RAG 与资产授权

- 向量 payload 持久化 `user_id`；Qdrant 物理 point ID 由用户和内部 entry ID 共同派生，防止不同用户的相同 entry ID 碰撞。
- payload 中的 `_id` 继续保留原始内部 entry/document ID，未改变调用方语义。
- Qdrant 与 FakeVectorStore 的 `get_by_ids`、count、文档列举、元数据检查支持租户过滤；fake 同样允许不同用户使用相同逻辑 ID。
- 知识入库保留并写入用户元数据；查询、文档列表、删除、上传状态均强制 `user_id` 过滤。
- RAG 工具在构造时绑定用户过滤条件；agent 无法通过生成不同参数取消租户过滤。
- 知识图片端点同时校验路径范围和向量元数据所有权；agent 内部 `read_image` 工具也接入相同的所有权检查边界。
- 简历上传 job、简历库元数据/内容/删除、线程简历草稿均校验所有者。线程简历文件使用用户目录和 thread ID 的 SHA-256 文件名，避免路径穿越及跨租户复用。
- 上传原文件采用用户目录作为 Task 3 的最小隔离点，解决不同用户同名文件互相覆盖；完整 UUID/注册表式存储仍留给 Task 4。

### 4. Checkpointer 内部命名空间

- 新增 `tenant_thread_id(user_id, thread_id)`，使用长度前缀生成无歧义内部 checkpoint thread ID。
- 新增 `tenant_checkpoint_config(...)`，复制原配置并仅替换 `configurable.thread_id`；公开 API 响应中的 thread ID 保持不变。
- 项目当前没有生产 checkpointer 调用链，因此在 LangGraph 编译/调用的实际集成边界验证：两个用户使用相同公开 thread ID 时，MemorySaver 恢复各自状态。

### 5. 旧数据迁移

- 新增 `scripts/migrate_legacy_tenant.py`，默认只 dry-run，只有传入 `--apply` 才写入，且不会自动执行。
- 默认选择最早创建的管理员；也可用 `--target-user` 明确目标。目标用户用于目录时进行安全校验。
- SQLite checkpoint：先创建备份，检测目标冲突后才更新旧 thread ID；重复运行不会重复变更。
- 简历线程文件：复制到新租户目录并保留源文件；简历元数据写入前备份，已归属记录跳过。
- Postgres：仅在显式提供 DSN 时于事务内归属旧 `u_001` 数据。
- Qdrant：先完整扫描，再按新租户物理 ID 复制，确认成功后删除旧 point；逻辑 `_id` 保持不变；目标冲突时不破坏任一记录。
- 本地 dry-run 结果：`changes=3 conflicts=0`（2 个旧简历线程文件、1 个旧简历元数据）；未写入任何数据。

## 测试与验证

测试环境：`careercrew` conda Python，仓库根目录加入 `PYTHONPATH`。

1. 完整单元测试

   ```powershell
   $env:PYTHONPATH=(Get-Location).Path
   F:\Python_develop\miniconda3\envs\careercrew\python.exe -m pytest -q tests/unit
   ```

   结果：282 passed；仅有 Qdrant local mode 不支持 payload index 的预期 warning。

2. API + 相关 integration/e2e

   ```powershell
   F:\Python_develop\miniconda3\envs\careercrew\python.exe -m pytest -q tests/api tests/integration/test_supervisor_agent_react.py tests/e2e/test_match_resume_loop.py
   ```

   结果：74 passed。

3. Task 3 聚焦回归

   ```powershell
   F:\Python_develop\miniconda3\envs\careercrew\python.exe -m pytest -q tests/api/test_tenant_isolation_api.py tests/unit/test_tenant_isolation.py tests/unit/test_tenant_migration.py tests/unit/test_read_image.py
   ```

   结果：16 passed；覆盖两个真实 AuthService 用户/JWT、相同公开 thread ID、伪造 body/query `user_id`、线程/画像/记忆、简历 job/库/线程草稿、知识 job/文档/检索/图片、实际 in-memory Qdrant、实际 LangGraph MemorySaver 以及迁移幂等性。

4. 迁移 dry-run

   ```powershell
   F:\Python_develop\miniconda3\envs\careercrew\python.exe scripts/migrate_legacy_tenant.py --target-user u_001 --skip-qdrant
   ```

   结果：DRY-RUN，`changes=3 conflicts=0`，没有写入。

5. 静态/补丁检查

- 相关 Python 文件 `py_compile` 通过。
- `git diff --check` 通过；仅显示 Windows 工作区 LF/CRLF 提示，无空白错误。

## 文件清单

### 生产代码

- `careercrew_api/auth/dependencies.py`
- `careercrew_api/schemas.py`
- `careercrew_api/runtime.py`
- `careercrew_api/routers/chat.py`
- `careercrew_api/routers/consult.py`
- `careercrew_api/routers/data.py`
- `careercrew_api/routers/interview.py`
- `careercrew_api/routers/knowledge.py`
- `careercrew_api/routers/resume.py`
- `careercrew_core/memory/threads.py`
- `careercrew_core/memory/injection.py`
- `careercrew_core/rag/pipeline_multimodal.py`
- `careercrew_core/state/checkpointer.py`
- `careercrew_core/state/__init__.py`
- `careercrew_core/tools/internal/rag_query.py`
- `careercrew_core/tools/internal/read_image.py`
- `careercrew_ai/vector_store/base_vector_store.py`
- `careercrew_ai/vector_store/qdrant_store.py`
- `scripts/migrate_legacy_tenant.py`

### 测试与测试适配

- `tests/api/test_tenant_isolation_api.py`
- `tests/unit/test_tenant_isolation.py`
- `tests/unit/test_tenant_migration.py`
- `tests/unit/test_read_image.py`
- `tests/api/conftest.py`
- `tests/api/test_data_api.py`
- `tests/api/test_resume_api.py`
- `tests/integration/test_supervisor_agent_react.py`
- `tests/unit/test_knowledge_history.py`
- `tests/unit/test_salary_query.py`
- `tests/unit/test_supervisor_router.py`
- `tests/unit/test_thread_state.py`

## 自审

- 身份边界：业务入口没有使用请求中的用户 ID；旧字段只能被忽略。
- 键空间：线程存储、runtime cache、向量物理 ID、checkpoint 内部 thread ID 均包含认证用户。
- 授权：列表、详情、删除、异步 job 状态、检索、图片工具的入口均检查所有者；跨租户访问与不存在一致。
- 兼容性：公开 thread ID 未变化；内部 `_id` 语义未变化；现有 FakeRuntime/FakeVectorStore 能模拟真实隔离行为；原 API 测试通过。
- 迁移安全：默认 dry-run、无自动迁移、写前备份/冲突检查、重复执行幂等；测试使用真实 SQLite 和内存 Qdrant 集成边界，不只断言构造的字典。
- 范围控制：没有重构 Task 4 规定的新存储架构，也没有修改 Task 5 的 streaming 协议。

## 关注事项

1. 当前 `careercrew_web` 未发现 bearer token 注入或登录态 bootstrap。后端业务路由按 Task 3 已开始强制认证，因此现有前端在未接入认证 token 时会收到 401。该 UI 登录/鉴权接入不属于本任务的后端租户隔离范围，需要后续任务明确处理。
2. Task 3 只为原始上传文件增加用户目录以阻止跨租户同名覆盖；同一用户并发上传同名文件仍可能覆盖。Task 4 应按既定要求完成 UUID 路径、资产注册表和完整路径迁移。
3. 未对外部 Postgres/Qdrant 实例执行迁移。脚本保持显式 dry-run/apply；真实环境应先 dry-run、检查冲突及备份，再单独授权执行。
