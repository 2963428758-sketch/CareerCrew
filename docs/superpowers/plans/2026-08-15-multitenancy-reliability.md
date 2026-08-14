# 多租户安全与会诊可靠性优化实施计划

## Global Constraints

- 在 `codex/reliability-multitenancy` 分支实施；保留既有单用户数据，并把 `u_001` 归属首个管理员。
- 身份认证采用本地账号、JWT 访问令牌与 HttpOnly/SameSite 刷新 Cookie；仅管理员可创建账号，生产环境不得使用缺省密钥。
- 一切租户边界以认证主体为准，不能信任客户端提交的 `user_id`；知识库默认私有。
- 原始上传文件按 UUID 存储，用户原文件名只保存为元数据；每次由磁盘路径访问文件前必须验证其处在获授权的根目录内。
- 只隔离新的上传；历史 `data/uploads` 文件只生成审计清单，必须显式执行迁移命令才会移动。
- SSE 取消为协作式：客户端断开或生成器关闭时触发共享 `CancellationEvent`；队列满时绝不永久阻塞，仅允许丢弃可合并文本块，终态事件必须受控投递。
- 流式空闲超时统一由 `CONSULT_STREAM_IDLE_TIMEOUT_SECONDS=300` 控制，所有用户可见提示使用同一个真实秒数。
- 不在本轮改为 asyncio/anyio 或外部作业队列；这是后续演进方向。
- 新增或修改代码的行级覆盖率门槛为 80%；发布门禁基于版本化评估基线的非回归，而非凭空设定绝对模型分数。

### Task 1: 修复 Postgres 情景记忆最新事件排序

修改 `careercrew_core/memory/db.py` 中 Postgres `latest_episodic` 查询为 `ORDER BY ts DESC, id DESC`。添加真实 Postgres 回归测试，覆盖不按插入顺序的时间戳及相同时间戳的 id 决胜；将该测试接入带 Postgres service 的 CI job。不得只修改内存 fake 或只增加字符串断言测试。

### Task 2: 本地账号、JWT 与管理员开户

新增认证和账户持久化层，提供 bootstrap、登录/token、刷新、登出、当前用户和管理员创建用户接口。使用密码哈希（Argon2 优先）和签名 JWT；访问 token 短期使用，刷新 token 仅放 HttpOnly/SameSite Cookie。开发可 bootstrap 第一个管理员，已有 `u_001` 数据要归属该管理员；生产缺失密钥要失败。为认证流程与管理员限制增加 API 测试。

### Task 3: 认证主体驱动的完整租户隔离

移除/忽略外部可控的用户身份来源，将 routes、ThreadStore、runtime `_cycles`、Qdrant 元数据及 record id、checkpointer 配置都以认证 `(user_id, thread_id)` 隔离。用户知识库默认私有，文档读取和图片资产也必须授权。增加可重复运行的 `u_001` 迁移脚本和双用户隔离 API 回归测试，涵盖线程、简历、知识库检索及 checkpoint。

### Task 4: 上传隔离、UUID 与路径安全

引入统一 storage 层与文档登记。新文件使用以下布局：

`data/uploads/resumes_raw/{user_id}/{upload_uuid}.{ext}`
`data/uploads/knowledge_raw/{user_id}/{upload_uuid}.{ext}`
`data/parsed/resumes/{user_id}/{upload_uuid}/`
`data/parsed/knowledge/{user_id}/{document_uuid}/`

原名只作 metadata。resume、knowledge、runtime 只扫描知识库目录，resume 不得自动入库。所有路径由 `resolve()` 加受限根目录检查构建。增加历史根目录审计清单与显式迁移命令（默认 dry-run），及重名、穿越、隔离、启动扫描回归测试。

### Task 5: 全部 SSE 流的取消、背压与回收

重构 `careercrew_api/sse.py` 及调用处：共享 `CancellationEvent`、非阻塞/有界队列写入与终态事件受控投递。生成器 `finally`、客户端断连和停止动作都发出取消；Agent、工具和会诊 orchestration 在自然边界检查取消，避免后续阶段/工具启动。队列满时只丢弃可合并 chunk，不能永久阻塞线程或丢失 error/done。补通用和会诊流的断连、取消、满队列、资源回收测试。

### Task 6: 会诊画像持久化与前端边界修复

将 `current_position` 纳入用户画像字段，支持显式清除且后续会诊可读取。前端将资料弹窗关闭状态按会话维度保存并在新会话重置；流错误删除或标记未填充的 assistant 占位消息，防止空气泡。以每个会话独立的人工验收流程和已有前端构建验证。

### Task 7: 分层 CI、覆盖率与首屏包拆分

CI 拆成快速单测、API、Postgres memory、编译/类型检查、前端 `npm ci && npm run build`；集成/e2e 置于 nightly/workflow_dispatch。对 PR changed lines 执行 80% coverage gate。前端通过 `React.lazy`/`Suspense` 拆分 Chat、Consult、Knowledge 等路由和重依赖页面，保持路由行为不变。

### Task 8: Agent/RAG 质量评估发布闭环

扩充 `data/eval/cases.jsonl`，覆盖路由、检索、引用、工具、会诊、记忆压缩；增加可离线运行的评估 runner 与版本化 `baseline.json`。输出 route accuracy、RAG Hit@K/MRR、citation coverage、tool success、consult latency/token、memory hit/retention，并以非回归基线作为 PR 发布门禁；依赖真实模型/服务的评估移至 nightly/manual。
