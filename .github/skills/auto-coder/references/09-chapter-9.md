## 9. 快速开始

> 开发/运行速查。自动开发直接说 `auto code`，auto-coder skill 走"同步 spec -> 找任务 -> 实现 -> 测试 -> 持久化"流水线。

### 9.1 环境准备

```bash
# conda env careercrew（Python 3.12，已建好）
conda activate careercrew
# BGE-M3 模型已下至 data/ms_cache/（ModelScope，HF 直连被拦）
# 模型路径: data/ms_cache/models/BAAI--bge-m3/snapshots/master
```

### 9.2 配置

```bash
# 1. 设硅基流动 API key（环境变量，不硬编码）
export SILICONFLOW_API_KEY="sk-xxx"            # Git Bash
# $env:SILICONFLOW_API_KEY="sk-xxx"            # PowerShell

# 2. 编辑 config/settings.yaml（见 §5.5 完整配置示例）
#    关键：llm.base_url 指向硅基流动、embedding.provider=bge_m3_local、rerank.backend=siliconflow
```

### 9.3 运行

```bash
conda run -n careercrew python -m careercrew_cli.app          # CLI 求职顾问
conda run -n careercrew python scripts/start_dashboard.py     # Streamlit Dashboard
conda run -n careercrew python scripts/ingest_knowledge.py data/knowledge/   # 知识库摄取
```

### 9.4 测试

```bash
conda run -n careercrew pytest -q tests/unit/         # 单元（秒级）
conda run -n careercrew pytest -q tests/integration/  # 集成（多组件协作）
conda run -n careercrew pytest -q tests/e2e/          # 端到端（求职闭环）
```

### 9.5 自动开发（auto-coder）

```bash
# 说 "auto code" -> 自动找下一个待办任务并实现
# 说 "auto code A1" -> 指定任务
# 说 "auto code --no-commit" -> 跑完不 commit
```

> 所有 python/pytest 命令都在 conda env `careercrew` 下（`conda activate careercrew` 或 `conda run -n careercrew ...`）。

---

> **文档状态**：初稿 v0.2（自建 RAG + 硅基流动 + conda env）。后续按实际开发迭代细化各节（尤其是排期子任务的修改文件列表与验收标准，需在实现中校正）。
> **决策记录**：见 `prompts/gen_dev_spec.md` 末尾"决策记录"小节（供参考，不写进 spec）。
