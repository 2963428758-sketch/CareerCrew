---
name: auto-coder
description: Autonomous spec-driven development agent. Syncs DEV_SPEC.md into chapter-based reference files, identifies the next pending task from the schedule, implements code following spec architecture and patterns, runs tests with up to 3 auto-fix rounds, and persists progress with atomic commits. Use when user says "auto code", "自动开发", "自动写代码", "auto dev", "一键开发", "autopilot", or wants fully automated spec-to-code workflow.
---

# Auto Coder

One trigger completes **read spec -> find task -> code -> test -> persist progress**.

Optional modifiers: append a task ID (e.g. `auto code B2`) to target a specific task, or `--no-commit` to skip git commit.

---

## Pipeline

```
Sync Spec -> Find Task -> Implement -> Test (≤3 fix rounds) -> Persist
```

Pause only at the end for commit confirmation. Run everything else autonomously.

> **⚠️ CRITICAL: 用 conda env `careercrew` 跑所有 `python`/`pytest` 命令。**
> - 激活（shell 内生效）：`conda activate careercrew`（Windows PowerShell / Git Bash / macOS/Linux 通用）
> - 或不激活直接调：`conda run -n careercrew python ...` / `conda run -n careercrew pytest ...`
> - env 路径（直接调 python 用）：`F:/Python_develop/miniconda3/envs/careercrew/python.exe`

## Reference Map

All files under `.github/skills/auto-coder/references/`:

| File | Content | When to Read |
|------|---------|-------------|
| `01-overview.md` | Project overview & goals | First task or when needing project context |
| `02-features.md` | Feature specifications | When implementing feature-related tasks |
| `03-tech-stack.md` | Tech stack & dependencies | When choosing libraries or patterns |
| `04-testing.md` | Testing conventions | When writing tests |
| `05-architecture.md` | Architecture & module design | When creating/modifying modules |
| `06-schedule.md` | Task schedule & status | Every cycle (Sync Spec step) |
| `07-future.md` | Future roadmap | When planning or assessing scope |
| `08-interview-mapping.md` | 面试考点与简历亮点映射 | When preparing interviews / writing resume bullets |
| `09-quickstart.md` | 快速开始（环境/配置/运行/测试） | When needing run commands / env setup |

---

### 1. Sync Spec

```bash
python .github/skills/auto-coder/scripts/sync_spec.py
```

Then read the schedule file to get task statuses:
- Read `.github/skills/auto-coder/references/06-schedule.md`

Task markers:

| Marker | Status |
|--------|--------|
| `[ ]` / `⬜` | Not started |
| `[~]` / `🔶` / `(进行中)` | In progress |
| `[x]` / `✅` / `(已完成)` | Completed |

---

### 2. Find Task

Pick the first `IN_PROGRESS` task, then the first `NOT_STARTED`. If user specified a task ID, use that directly.

Quick-check predecessor artifacts exist (file-level only). On mismatch, log a warning and continue - only stop if the target task itself is blocked.

---

### 3. Implement

1. **Read relevant spec** from `.github/skills/auto-coder/references/`:
   - Architecture: `05-architecture.md`
   - Tech details: `03-tech-stack.md`
   - Testing conventions: `04-testing.md`

2. **Extract** from spec: inputs/outputs, design principles (Hybrid 架构? 3 层记忆? HITL 闸门? 配置驱动? 向量库可插拔?), file list, acceptance criteria.

3. **Plan** files to create/modify before writing any code.

4. **Code** - project-specific rules:
   - Treat spec as single source of truth
   - Use `config/settings.yaml` values, never hardcode
   - Match existing codebase patterns and style
   - Respect one-way dependency: `careercrew_ai` -> `careercrew_core` -> `careercrew_api`; core 只发事件不碰渲染, `careercrew_web/` 独立前端
   - 自建 RAG 为主（ADR-2：不依赖外部 RAG 项目）；复用本仓已有抽象（careercrew_ai 的 Base* 工厂 / careercrew_core 的 registry 等），不重复造轮子
   - MVP first; 高级方向 only when explicitly tasked (spec 中标注【高级方向】的项不自动实现)

5. **Write tests** alongside code:
   - Place in `tests/unit/` or `tests/integration/` per spec
   - Mock external deps (LLM / Milvus / MCP) in unit tests

6. **Self-review** before running tests: verify all planned files exist and tests import correctly.

---

### 4. Test & Auto-Fix

```

Round 0..2:
  Run pytest on relevant test file
  If pass -> go to step 5
  If fail -> analyze error, apply fix, re-run

Round 3 still failing -> STOP, show failure report to user
```

---

### 5. Persist

1. **Update `docs/DEV_SPEC.md`** (global file): change task marker `[ ]` -> `[x]`
2. **Re-sync**: `python .github/skills/auto-coder/scripts/sync_spec.py --force`
3. **Show summary & ask**:

```
✅ [A3] 配置加载与校验 - done
   Files: careercrew_core/state/settings.py, tests/unit/test_config_loading.py
   Tests: 8/8 passed
   Commit: feat(config): [A3] implement config loader

   "commit" -> git add + commit
   "skip"   -> end
   "next"   -> commit + start next task
```

On "next", loop back to step 1 and start the next task.
