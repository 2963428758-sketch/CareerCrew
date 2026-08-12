# CareerCrew

多智能体**职业顾问团队**系统 —— 长期陪跑用户整个求职周期：职位匹配、简历定制、面试模拟、薪资谈判、职业规划。

- **Hybrid Agent 架构**：LangGraph supervisor 编排 + agent 节点内 LangChain 1.x `create_agent` 执行链（LLM/工具/循环/流式事件由平台提供）。
- **三层记忆**（仿 Hermes）：短期 Context Window / 情景 append-only 树 / 长期 User Model。
- **自建 RAG（多模态）**：BGE-M3 三合一（dense+sparse+colbert）+ Contextual Chunking + Hybrid/RRF + bge-reranker + VLM 看图，向量库 Qdrant；PDF/图片/docx 走 MinerU 云端精准解析 API（本机零推理负载，`rag.loaders.provider=api`）。
- **HITL 闸门**：高 stakes 决策（投递/接 offer/谈薪）默认人工确认。
- **可观测**：LangSmith 全链路追踪（LLM/工具/ReAct/HITL/RAG/记忆），默认脱敏上传，直接在 LangSmith 控制台查看。
- **本地优先**：Postgres / Qdrant 跑在本地 Docker（通用容器，非项目专属）；LLM/Rerank 走硅基流动 API。

> 详细设计见 [docs/DEV_SPEC.md](docs/DEV_SPEC.md)（架构 / 目录树 / 排期 A1–N5 / ADR / 面试映射）。

## 快速开始

```bash
# 1. 环境（conda env careercrew，Python 3.12，已建好）
conda activate careercrew

# 2. 安装项目（核心依赖 + 测试工具链）
pip install -e ".[dev]"
#   评估（Ragas）：pip install -e ".[eval]"

# 3. 配置 API key（.env 或环境变量；.env 已被 gitignore）
export SILICONFLOW_API_KEY="sk-xxx"        # Git Bash
# $env:SILICONFLOW_API_KEY="sk-xxx"        # PowerShell
export LANGSMITH_API_KEY="lsv2_xxx"        # LangSmith 追踪（可选，缺失时自动禁用）
# $env:LANGSMITH_API_KEY="lsv2_xxx"

# 3.5 启动本地依赖（Postgres + Qdrant，通用容器，跨项目共用）
docker run -d --name postgres --restart unless-stopped -p 5432:5432 \
  -e POSTGRES_USER=careercrew -e POSTGRES_PASSWORD=careercrew -e POSTGRES_DB=careercrew \
  -v postgres-data:/var/lib/postgresql/data postgres:16
docker run -d --name qdrant --restart unless-stopped -p 6333:6333 -p 6334:6334 qdrant/qdrant

# 国内网络访问 LangSmith 需走本地代理（Clash 默认 127.0.0.1:7890）
# $env:HTTPS_PROXY="http://127.0.0.1:7890"; $env:HTTP_PROXY="http://127.0.0.1:7890"

# 4. 运行
conda run -n careercrew uvicorn careercrew_api.main:app --reload --port 8000   # Web 前端 + API

# 5. 测试
conda run -n careercrew pytest -q tests/unit/
```

## 目录结构

| 包 | 职责 |
|----|------|
| `careercrew_ai` | LLM 适配 / embedding(BGE-M3) / reranker / vector_store / `create_agent` 执行链 |
| `careercrew_core` | LangGraph supervisor + 6 agent + 记忆 + 工具注册表 + state + 自建 RAG + 求职周期工作流 |
| `careercrew_api` | FastAPI（SSE 流式 + 会诊 + 记忆/线程管理），生产托管 `careercrew_web/dist` |
| `careercrew_mcp` | 自建 MCP server |
| `careercrew_web/` | React + Vite 前端（求职对话 / 会诊 / 面试 / 简历 / 知识库 / 数据） |

依赖方向：`careercrew_ai` → `careercrew_core` → `careercrew_api`（单向，core 只发事件不碰渲染）。

## 状态

MVP 开发中（阶段 A 工程骨架）。进度跟踪见 [docs/DEV_SPEC.md §6 进度表](docs/DEV_SPEC.md)。
