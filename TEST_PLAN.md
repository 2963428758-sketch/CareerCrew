# CareerCrew 全量测试计划（阶段 L 收尾验收）

> 目标：对 CLI 全量功能 + Streamlit Dashboard 做完整测试，发现 bug 即修，确保所有功能通过后才结束。
> 环境：conda env `careercrew`；所有命令 `conda run -n careercrew ...` 或直接调 env python。

## 一、CLI / 功能测试用例

| # | 用例 | 命令 | 预期 |
|---|------|------|------|
| C1 | 版本 | `careercrew --version` | 输出版本 0.1.0，exit 0 |
| C2 | 配置校验 | `careercrew config` | 配置校验通过，打印 LLM/Embedding/Rerank/VectorStore |
| C3 | chat 启动/退出 | `echo "退出" \| careercrew chat` | banner + 提示 + 正常退出，无报错 |
| C4 | ReAct demo | `python scripts/demo_react.py` | 路由表 + 真实 LLM 调 search_jobs + 最终答案 |
| C5 | 记忆 demo | `python scripts/demo_memory.py` | JSONL 树 + 回溯链 + User Model 落盘 + 非法字段拒绝 |
| C6 | RAG demo | `python scripts/demo_rag.py` | ingest 知识库 + 3 问检索命中(score>0.5) |
| C7 | 匹配官 demo | `python scripts/demo_job_matcher.py` | 搜 JD + rag_query JD库 + job_match 写记忆 |
| C8 | 简历顾问 demo | `python scripts/demo_resume_advisor.py` | rag_query 简历范本 + 定制简历 + 匹配度 |
| C9 | 面试官 demo | `python scripts/demo_interviewer.py` | rag_query 出题 + 评分 + 写 interview_qa |
| C10 | 单元/集成/E2E | `pytest -q tests/` | 150 全绿 |
| C11 | 编译 | `compileall careercrew_*` | 无语法错误 |

## 二、Streamlit Dashboard 浏览器自动化测试

> 启动：`streamlit run careercrew_ui/dashboard/app.py`（localhost:8501）；用 bb-browser 打开 + 快照 + 点击切换页面。

| # | 用例 | 操作 | 预期 |
|---|------|------|------|
| D1 | Dashboard 启动 | bb-browser open localhost:8501 | 页面加载，标题 CareerCrew Dashboard |
| D2 | 系统总览页（默认） | snap | 显示组件配置(LLM/Embedding) + 记忆统计 |
| D3 | 数据浏览页 | click 侧边栏"数据浏览" | 显示 User Model + 情景记忆树 |
| D4 | 追踪查看页 | click 侧边栏"追踪查看" | 显示 trace 类型统计 + traces.jsonl 内容 |
| D5 | 控制台无报错 | preview_console_logs / bb-browser 日志 | 无异常 |

## 三、已知风险/检查点

- Milvus Lite 锁：多次运行会留僵尸进程，测试前清理（taskkill python.exe）。
- RAG demo（C6）contextual=True 慢(~3min)，超时转后台处理。
- Dashboard 数据依赖 data/user_model.json / transcripts / logs/traces.jsonl，跑过 CLI/demo 后有数据可渲染。

## 四、执行与修复流程

1. 先跑 CLI 用例 C1-C5、C10、C11（快），发现 bug 记入下方"问题日志"并修复。
2. 再跑慢用例 C6-C9（真实 LLM，各 ~1-3min）。
3. 启动 Dashboard，bb-browser 跑 D1-D5。
4. 修复所有问题后重跑相关用例，直至全绿。

## 五、问题日志

| 日期 | 用例 | 问题 | 修复 |
|------|------|------|------|
| 2026-07-30 | C3 | chat 初始化失败 `JobMatcher got unexpected keyword 'tracer'`：BaseAgent 加了 tracer 但 5 个 agent 子类未透传 | 5 个子类 __init__ 加 tracer 并透传 super；加回归测试 |
| 2026-07-30 | D1/D2 | Streamlit 1.61 自动多页导航(app/data browser/overview/traces)与 st.sidebar.radio 重复，且 auto 导航页空白 | `.streamlit/config.toml` `client.showSidebarNavigation=false` 隐藏 auto 导航 |
| 2026-07-30 | C6 | demo_rag 每次用 contextual=True 重 ingest 全库(~15min)过慢 | 改为 KB 已入库(count>0)则跳过 ingest；清理未用 import |
| 2026-07-30 | C6 | 中断 contextual ingest 会把 KB 覆盖成混合状态(检索分降) | 清空 Milvus + 干净 ingest(contextual=False)；12 问命中率恢复 9/12 |

## 六、测试结果汇总

- **CLI**：C1-C11 全部通过（真实 LLM demos：ReAct/记忆/RAG/匹配/简历/面试 均端到端产出正常；pytest 150+ 全绿）。
- **Dashboard**：D1-D5 通过（3 页面经 bb-browser 浏览器自动化验证渲染，auto 导航 bug 已修）。
- **KB 质量**：12 问命中率 9/12（恢复；3 弱命中为已知弱主题，见 DEV_SPEC §3.7.5）。
