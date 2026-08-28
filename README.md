# CareerCrew

多智能体职业顾问团队系统 —— 由 LangGraph supervisor 编排职位匹配、简历定制、面试模拟、薪资谈判、职业规划等多个 AI 顾问 agent，围绕自建多模态 RAG、三层记忆与 HITL 人工确认闸门，长期陪跑用户整个求职周期。

> 架构设计、ADR 与排期详见 [docs/DEV_SPEC.md](docs/DEV_SPEC.md)；备份运维见 [docs/OPS_BACKUP.md](docs/OPS_BACKUP.md)。

## 功能介绍

**多智能体协作**

- 6 个专职 agent：职位匹配官 JobMatcher、简历顾问 ResumeAdvisor、面试官 Interviewer、薪资谈判师 SalaryNegotiator、职业规划师 CareerPlanner、知识库顾问 KnowledgeAdvisor
- LangGraph supervisor 按阶段路由（intent / planning / match / resume / interview / negotiate / apply / track / review），agent 节点内由 LangChain 1.x `create_agent` 执行 LLM + 工具循环
- 多顾问会诊：LLM 编排器多轮并行分派 → 各顾问独立意见 → 综合结论；缺少背景资料时可向前端下发资料填写表单
- HITL 闸门：高风险动作（`submit_application` 投递简历等）默认拦截等待用户确认；apply 阶段直接终止图执行
- 内部工具集：`rag_query` / `memory_search` / `memory_write` / `profile_update` / `search_jobs`（CDP 接管 Boss直聘 + 猎聘真实岗位，库缓存优先）/ `salary_query` / `read_image` / `submit_application`

**自建多模态 RAG**

- 文档解析：md / txt 直读；PDF、图片、docx、pptx、xlsx 走 MinerU（默认云端 API 精准解析，可切本地子进程），产出页面 Markdown 与对象裁剪图
- 分块：递归分块（800/100）；可选 Contextual Chunking（LLM 为每块生成文档级上下文前缀，`rag.chunking.contextual` 开启，默认关闭——每块一次 LLM 调用，摄取成本较高）
- 检索：BGE-M3 本地三合一向量（dense + sparse + colbert）写入 Qdrant → 混合召回 → 客户端 RRF 融合 → 硅基流动 rerank 精排（多模态走 Qwen3-VL-Reranker）
- 回答：VLM（GLM-4.5V）看页面/裁剪图作答并返回引用来源；Agentic RAG 支持 kb/web/memory 路由与多跳子查询分解

**三层记忆（仿 Hermes）**

- 短期：Context Window 按 token 裁剪与压缩（compaction，压缩前先抽取关键信息入语义事实）
- 情景：append-only 事件树（Postgres 存储 + Qdrant 向量索引）
- 长期：语义事实 / 用户画像，由 LLM 路由按预算注入每次对话；后台 "Auto Dream" 定期合并去重（记忆系统默认关闭，需显式开启）

**Web 应用（React + FastAPI，NDJSON 流式）**

- 页面：求职规划对话、岗位匹配、模拟面试（逐题评分反馈）、简历定制与简历库、知识库问答与管理、多顾问会诊、个人设置、用户管理（admin）、质检工作台（quality_reviewer）
- 对话体验：流式渲染、停止 / 重新生成（版本切换）、@ 引用知识库文档与简历、聊天附件（≤25MB，每会话 ≤5 个，7 天过期，可转存知识库）、会话置顶 / 重命名 / 清空 / 导出 MD·JSON、会话内搜索、明暗主题
- 认证与多租户：argon2 密码哈希、JWT access token + HttpOnly 刷新 Cookie 轮换、登录失败锁定、admin / user / quality_reviewer 三种角色、数据按 owner 隔离
- 质量闭环：消息点赞点踩 → bad-case 归因复盘（脱敏快照 + 诊断元数据）→ 升级为评测 case → 离线评测回归门禁

**可观测性**：LangSmith 全链路追踪（LLM / 工具 / ReAct / HITL / RAG / 记忆），默认脱敏上传（截断 + 手机号 / 邮箱 / 薪资打码）

## 技术栈

| 分类 | 技术 |
|------|------|
| Backend | Python 3.12、FastAPI、Uvicorn、Pydantic v2 |
| Agent / 编排 | LangGraph ≥1.2（supervisor + interrupt/Command）、LangChain ≥0.3（`create_agent`）、langgraph-checkpoint-postgres、MCP（`mcp` SDK） |
| AI / LLM | 硅基流动 OpenAI 兼容 API（默认模型 `zai-org/GLM-4.5V`）、BGE-M3 本地 embedding（FlagEmbedding）、`bge-reranker-v2-m3` / `Qwen3-VL-Reranker-8B` 远程精排、MinerU 云端文档解析 |
| Database | PostgreSQL 16（账号 / 会话 / 记忆 / checkpointer 唯一关系库）、Qdrant（唯一向量库，混合 dense+sparse） |
| Frontend | React 19、TypeScript、Vite 8、Tailwind CSS 3.4、Zustand、react-router-dom 7、react-markdown |
| Testing | pytest（pytest-mock / pytest-check / pytest-cov）、Vitest + Testing Library、diff-cover 变更行覆盖率门禁 |
| DevOps | GitHub Actions 分层 CI |
| 第三方服务 | 硅基流动（LLM / rerank / VLM）、MinerU（文档解析）、LangSmith（追踪，可选）、阿里云 OSS（头像存储，可选）、Exa（仅 `scripts/fetch_kb.py` 抓语料用） |

## 项目结构

```text
CareerCrew/
├── careercrew_ai/        # LLM 适配 / BGE-M3 embedding / reranker / Qdrant vector_store / splitter / create_agent 执行链 / prompts
├── careercrew_core/      # supervisor + agents + 三层记忆 + 工具注册表 + 自建 RAG + 会话存储 + 配置加载
├── careercrew_api/       # FastAPI 应用（auth / routers / NDJSON 流式 / 附件 / OSS 头像）
├── careercrew_mcp/       # 自建 MCP server「careercrew-mm-rag」（multimodal RAG 工具）
├── careercrew_web/       # React + Vite 前端（生产构建产物 dist/ 由后端托管）
├── config/
│   ├── settings.yaml        # 主配置（${VAR} 占位符从环境变量替换）
│   └── settings.docker.yaml # 容器部署变体（production 环境口径，与主配置字段保持对齐）
├── scripts/              # 知识入库 / 数据迁移 / 评估 / 清理脚本
├── tests/                # pytest：unit / integration / e2e / api
├── docs/                 # 设计文档（DEV_SPEC / RAG / LangSmith / 前端方案 / 运维备份）
├── data/                 # 运行时数据（uploads / parsed / db / eval；大部分已 gitignore）
├── migrations/           # Alembic 迁移（0001_baseline 为 pg_dump 全量 schema 快照）
├── alembic.ini           # schema migration 唯一入口
├── Dockerfile            # 多阶段构建（builder 装依赖到独立 venv，runtime 携带产物）
├── docker-compose.yml    # 一键编排：postgres + qdrant + app
├── .github/workflows/    # CI 流水线（含 docker build 冒烟 / pip-audit / dependabot）
├── pyproject.toml        # Python 依赖、ruff 与 pytest 配置
└── .env                  # 本地密钥（已 gitignore，勿提交；模板见 .env.example）
```

依赖方向：`careercrew_ai` → `careercrew_core` → `careercrew_api`（单向）。

## 环境要求

- **Python 3.12**（`requires-python = ">=3.12,<3.13"`，其他版本不可用）
- **Node.js 22**（CI 使用版本；前端开发构建需要）
- **Docker**（运行 PostgreSQL 16 与 Qdrant 官方镜像）
- **BGE-M3 本地模型权重**（约 2GB；下载后将路径填入 `config/settings.yaml` 的 `embedding.model_path`，默认值是开发者本机路径，必须修改）
- **API Key**：硅基流动（必需）；MinerU（文档解析 `rag.loaders.provider=api` 时必需）
- **Google Chrome**（岗位匹配实时抓取需要：通过 CDP 调试端口接管已登录的 Boss直聘 与 猎聘）

## 快速开始

### 1. 克隆项目

```bash
git clone <repository-url>
cd CareerCrew
```

### 2. 配置环境变量

```bash
cp .env.example .env   # 然后按需填写
```

本地开发必填 `DASHSCOPE_API_KEY` 与 `DATABASE_URL`；容器部署由 compose 注入 `DATABASE_URL`，另需 `AUTH_JWT_SECRET`（≥32 字符）。各变量含义见 [配置说明](#配置说明)，完整模板见 [.env.example](.env.example)。

> `.env` 已被 `.gitignore` 排除（含 `!.env.example` 否定规则），**绝不提交真实密钥**。

### 3. 安装依赖

```bash
# 后端（核心依赖 + Web + 测试工具链；含 FlagEmbedding/torch 等重 ML 栈，首次安装体积较大）
pip install -e ".[dev,web]"
# 可选：答案级评估（Ragas）
pip install -e ".[eval]"
```

```bash
# 前端
cd careercrew_web
npm install
cd ..

# （可选）启动 Chrome CDP 调试实例以开启 Boss直聘/猎聘 真实岗位实时抓取：
# 运行脚本自动调起 Chrome，并在打开的页面中分别登录 Boss直聘 与 猎聘 即可：
powershell -ExecutionPolicy Bypass -File scripts/start_chrome_cdp.ps1
```

### 4. 启动基础服务

本地开发可直接用 compose 起依赖（跳过 app 服务）：

```bash
docker compose up -d postgres qdrant
```

或用通用容器手动启动：

```bash
docker run -d --name postgres --restart unless-stopped -p 5432:5432 \
  -e POSTGRES_USER=careercrew -e POSTGRES_PASSWORD=careercrew -e POSTGRES_DB=careercrew \
  -v postgres-data:/var/lib/postgresql/data postgres:16

docker run -d --name qdrant --restart unless-stopped -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

> 完整三服务一键编排见 [容器部署](#容器部署)。

### 5. 启动项目

```bash
# 后端 API（首个请求触发重组件惰性加载，约 10–30 秒属正常）
uvicorn careercrew_api.main:app --reload --port 8000
```

```bash
# 前端开发模式（端口固定 5175，/api 代理到 8000）
cd careercrew_web
npm run dev
```

打开 <http://localhost:5175>，首次使用在登录页创建初始管理员（仅 development 环境可用，对应 `POST /api/auth/bootstrap`）。

**生产模式**：前端构建后由后端单端口托管：

```bash
cd careercrew_web && npm run build   # 产物输出到 careercrew_web/dist
uvicorn careercrew_api.main:app --port 8000   # 检测到 dist/ 即自动托管 + SPA fallback
```

## 配置说明

加载顺序：`.env`（python-dotenv，优先级最高）→ `config/settings.yaml`（`${VAR}` 占位符做环境变量替换）→ pydantic 校验（缺关键字段 fail-fast 抛 `SettingsError`）。主配置分段见 `config/settings.yaml` 注释（llm / embedding / rerank / vector_store / rag / vlm / supervisor / memory / tools / hitl / langsmith / oss / auth）。

`.env` 环境变量：

| 变量 | 必填 | 说明 |
|------|------|------|
| `DASHSCOPE_API_KEY` | ✅ | 阿里云百炼平台密钥，通义千问 LLM / gte-rerank / qwen-vl 调用均使用 |
| `DATABASE_URL` | ✅ | PostgreSQL 连接串（账号 / 会话 / 记忆 / checkpoint 共用） |
| `MINERU_API_KEY` | 视配置 | MinerU 云端解析 token；`rag.loaders.provider: api`（默认值）时必填 |
| `AUTH_JWT_SECRET` | 生产必填 | JWT 签名密钥，生产环境要求 ≥32 字符；development 下缺省时进程内随机回退 |
| `AUTH_DATABASE_URL` | 否 | 认证库独立 DSN，未设置时回退 `DATABASE_URL` |
| `LANGSMITH_API_KEY` | 否 | LangSmith 追踪密钥，缺失时自动禁用追踪 |
| `CAREERCREW_ENV` | 否 | 运行环境覆盖（默认 development；production 会强制校验认证安全配置） |
| `CAREERCREW_AGENT_VERSION` | 否 | agent 版本标记（进入追踪与评测记录） |
| `OSS_ENDPOINT` / `OSS_ACCESS_KEY_ID` / `OSS_ACCESS_KEY_SECRET` / `OSS_BUCKET_NAME` | 否 | 阿里云 OSS 头像存储；任一缺失则回退本地 `data/uploads/avatars/` |
| `POSTGRES_TEST_DSN` | 测试 | 集成测试使用的数据库连接串 |

## 服务地址

| 服务 | 地址 |
|------|------|
| Frontend（开发模式） | <http://localhost:5175> |
| Backend / API（同时托管前端生产构建） | <http://localhost:8000> |
| Swagger UI | <http://localhost:8000/docs> |
| ReDoc | <http://localhost:8000/redoc> |
| OpenAPI Schema | <http://localhost:8000/openapi.json> |
| Liveness 探针（无鉴权） | <http://localhost:8000/healthz> |
| Readiness 探针（Postgres/Qdrant 连通性，无鉴权） | <http://localhost:8000/readyz> |
| 组件级健康明细（需登录） | <http://localhost:8000/api/health> |
| Qdrant | <http://localhost:6333>（HTTP）/ 6334（gRPC） |
| PostgreSQL | localhost:5432 |

## API 文档

FastAPI 默认文档页开启：Swagger UI `/docs`、ReDoc `/redoc`、OpenAPI Schema `/openapi.json`。所有业务路由挂在 `/api` 前缀下；流式接口统一返回 NDJSON（事件类型 `stage` / `chunk` / `agent_start` / `agent_end` / `done` / `error` / `input_request`）。

## 容器部署

仓库提供多阶段 `Dockerfile` 与一键编排 `docker-compose.yml`（postgres + qdrant + app 三服务，克隆即跑）：

```bash
cp .env.example .env          # 填 DASHSCOPE_API_KEY / AUTH_JWT_SECRET（≥32 字符）
mkdir -p models/bge-m3        # 放置 BGE-M3 权重（只读挂载进容器 /models/bge-m3）
docker compose up -d --build
curl http://localhost:8000/readyz   # {"status":"ready","checks":{"postgres":"ok","qdrant":"ok"}} 即就绪
```

- 镜像分层：依赖安装层仅随 `pyproject.toml` 变化重建，业务代码改动命中缓存秒级完成；CPU torch 单独预装避免拉 CUDA 版
- app 容器启动先跑 `alembic upgrade head` 再起 uvicorn（迁移失败即退出，不做半启动）；compose 注入的 `postgresql+psycopg://` 方言 DSN 应用侧自动归一兼容
- 非 root 运行；数据落 `app_uploads` 卷（上传/解析产物）；镜像与 compose 均带 healthcheck
- 生产加固：`auth.cookie_secure` 在容器配置中已为 true（现代浏览器对 http://localhost 视为可信上下文）；有域名/LB 时在 `config/settings.docker.yaml` 的 `auth.trusted_origins` 追加

裸 `docker build -t careercrew .` 也可单独构建镜像。常用容器操作：

```bash
docker compose logs -f app     # 跟踪应用日志
docker compose ps              # 三服务健康状态
docker compose down            # 停止（加 -v 连数据卷一起删）
```

## 数据库

- **PostgreSQL 16** 是唯一关系库：账号（`auth_accounts` 等 4 张认证表）、会话（`conversations` / `conversation_turns` / `messages` / `agent_runs` 等）、记忆（情景事件 / 语义事实 / 记忆策略）、聊天附件、LangGraph checkpoint。
- **Schema 迁移统一走 Alembic**：根目录 `alembic.ini` + `migrations/`（0001_baseline 为 pg_dump 全量快照，24 表）。容器部署在应用启动前自动 `alembic upgrade head`；本地手动执行 `alembic upgrade head` 即可初始化。各 store 保留惰性建表作为开发兜底，并有双库一致性守卫测试（`tests/integration/test_alembic_baseline.py`）拦住漂移——新增字段一律走新 migration。
- **Qdrant** 集合 `careercrew_mm`（知识库）与 `careercrew_episodic_v2`（情景记忆）由应用自动创建。
- 历史数据迁移脚本见 `scripts/migrate_*.py`（默认 dry-run，`--apply` 生效）；备份恢复流程见 [docs/OPS_BACKUP.md](docs/OPS_BACKUP.md)。

## 测试

后端（pytest，marker 定义见 `pyproject.toml`）：

```bash
pytest -q tests/unit/                        # 单元测试（90 个文件，无需外部服务）
pytest -q tests/api                          # API 测试（FakeRuntime 注入，但需本机 Postgres 在跑）
pytest -q -m integration                     # 集成测试（需环境变量 POSTGRES_TEST_DSN）
pytest -q -m "integration or e2e"            # 含求职闭环 e2e
```

marker：`integration`（多组件集成）/ `e2e`（端到端）/ `slow`（慢测试）/ `web`（FastAPI 测试，CI 的 api job 每次运行）。

前端（Vitest，测试文件与源码同目录 `*.test.ts(x)`）：

```bash
cd careercrew_web
npm test          # vitest run
npm run lint      # oxlint
npm run build     # tsc -b && vite build（类型检查随构建）
```

评测回归门禁（CI 中同样执行）：

```bash
python scripts/eval_runner.py --offline --compare data/eval/baseline.json --fail-on-regression
```

## 开发规范

- **Commit**：历史提交遵循 Conventional Commits（`feat:` / `fix:` 前缀）；无正式 CONTRIBUTING 文档
- **Python 静态检查**：ruff（配置在 `pyproject.toml [tool.ruff]`，CI typecheck job 执行 `ruff check` + `compileall`）；mypy 渐进接入见 docs/TECH_DEBT_PLAN.md
- **前端**：oxlint 做 lint，`tsc -b` 随构建做类型检查
- **CI**（GitHub Actions）：push main / PR 触发 unit、api（Postgres 服务容器 + 覆盖率）、postgres-memory、typecheck、frontend、eval-sanity、docker-build（镜像构建 + 容器内 Alembic 迁移冒烟）、security-audit（pip-audit）八类任务 + diff-cover 变更行覆盖率 ≥80% 门禁；dependabot 周检五类生态依赖；nightly 定时跑 integration / e2e（阻塞口径，真实模型评测除外）
- **分支规范**：待补充

## 常见问题

| 现象 | 原因与处理 |
|------|-----------|
| 前端启动报端口占用退出 | Vite 配置了 `strictPort: true`（5175 固定），释放端口或改 `vite.config.ts`（注意同步 `auth.trusted_origins`） |
| 后端启动即抛 `SettingsError` | `.env` 缺少必填变量（`DASHSCOPE_API_KEY` / `DATABASE_URL`），或 `config/settings.yaml` 字段非法 |
| 接口返回 503「AI 服务暂不可用」 | Qdrant / Postgres 未启动，或重组件初始化失败；确认两个容器在跑后重试 |
| 首个请求卡住 10–30 秒 | 正常现象：embedding 等重组件按需惰性加载 |
| 启动时报 BGE-M3 模型路径错误 | `config/settings.yaml` 的 `embedding.model_path` 默认是开发者本机路径，改为本地实际权重路径 |
| 登录提示锁定 | 连续失败 5 次锁定 15 分钟（按用户名+IP 计数），稍后再试 |
| `search_jobs` 无法获取岗位或提示未配置 | 职位搜索优先读本地 jobs 库缓存；实时抓取使用已登录 Chrome 的 CDP 调试通道（端口 9222），请运行 `scripts/start_chrome_cdp.ps1` 并在浏览器中登录 Boss 直聘与猎聘 |
| 文档 / 简历解析失败 | `MINERU_API_KEY` 未配置（`provider: api` 时必需），或文件超出大小上限（简历 20MB / 知识库 50MB / 附件 25MB） |
| 国内访问百炼 / LangSmith 超时 | 配置代理（如 Clash `http://127.0.0.1:7890`）后重试 |

## 安全说明

- `.env` 已被 `.gitignore` 排除，**绝不提交**其中的 API Key、数据库密码、OSS AccessKey、JWT 密钥；SSH 私钥同理不应出现在仓库中
- 所有敏感配置通过 `${VAR}` 占位符从环境变量注入 `config/settings.yaml`，不要把真实值写进代码、配置文件或文档
- 生产部署必须：设置 `CAREERCREW_ENV=production`（启动时强制校验 `AUTH_JWT_SECRET` ≥32 字符）、`auth.cookie_secure` 改为 `true`、收紧 `auth.trusted_origins`
- 初始管理员仅能经 bootstrap 接口创建（限 development 环境）；管理员开户时密码留空则默认 `123456` 并强制首次登录修改，自定义密码则可直接登录
- 敏感信息建议统一使用环境变量或 Secret 管理服务注入，避免明文落盘

## License

`pyproject.toml` 中声明为 **MIT**；仓库根目录暂无 LICENSE 文件（待补充）。
