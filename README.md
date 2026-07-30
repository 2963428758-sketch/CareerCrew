# CareerCrew

多智能体**职业顾问团队**系统 —— 长期陪跑用户整个求职周期：职位匹配、简历定制、面试模拟、薪资谈判、职业规划。

- **Hybrid Agent 架构**：LangGraph supervisor 编排 + agent 节点内手写 ReAct 循环（可见 while，不依赖黑盒）。
- **三层记忆**（仿 Hermes）：短期 Context Window / 情景 append-only 树 / 长期 User Model。
- **自建 RAG**：BGE-M3 三合一（dense+sparse+colbert）+ Contextual Chunking + Hybrid/RRF + bge-reranker，向量库 Milvus Lite（Chroma 兜底）。
- **HITL 闸门**：高 stakes 决策（投递/接 offer/谈薪）默认人工确认。
- **本地优先**：Milvus Lite / SQLite / JSONL 零外部服务；LLM/Rerank 走硅基流动 API。

> 详细设计见 [DEV_SPEC.md](DEV_SPEC.md)（架构 / 目录树 / 排期 A1–N5 / ADR / 面试映射）。

## 快速开始

```bash
# 1. 环境（conda env careercrew，Python 3.12，已建好）
conda activate careercrew

# 2. 安装项目（核心依赖 + 测试工具链）
pip install -e ".[dev]"
#   D 阶段装向量库：pip install -e ".[milvus]"
#   L 阶段装评估/UI：pip install -e ".[eval,ui]"

# 3. 配置硅基流动 API key
export SILICONFLOW_API_KEY="sk-xxx"        # Git Bash
# $env:SILICONFLOW_API_KEY="sk-xxx"        # PowerShell

# 4. 运行
careercrew --version
conda run -n careercrew python -m careercrew_cli.app

# 5. 测试
conda run -n careercrew pytest -q tests/unit/
```

## 目录结构（四层单向依赖）

| 层 | 包 | 职责 |
|----|----|------|
| AI 层 | `careercrew_ai` | LLM 适配 / embedding(BGE-M3) / reranker / vector_store / 手写 ReAct 内核 |
| 核心层 | `careercrew_core` | LangGraph supervisor + 5 agent + 记忆 + 工具注册表 + state + 自建 RAG |
| 产品层 | `careercrew_cli` | 求职周期工作流编排 + HITL 闸门 + CLI 入口 |
| UI 层 | `careercrew_ui` | CLI 渲染 + Streamlit Dashboard |

依赖方向：`careercrew_ai` → `careercrew_core` → `careercrew_cli` → `careercrew_ui`（单向，core 只发事件不碰渲染）。

## 状态

MVP 开发中（阶段 A 工程骨架）。进度跟踪见 [DEV_SPEC.md §6 进度表](DEV_SPEC.md)。
