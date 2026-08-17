# T1.5 报告 — prompt_version sha256 + agent_version git-sha 落地（Phase 1）

## 状态：DONE

## 提交

- `5185788` feat(versioning): sha256 prompt versions and git-sha agent version

## 实现内容

### 新增 `careercrew_core/versioning.py`

- `prompt_version(text: str | None) -> str`：UTF-8 编码 → sha256 → `sha256:<64 hex 小写>`；
  空文本 / None / 纯空白 → `"unversioned"`。绝不返回 `unknown`。
- `agent_version() -> str`：模块级缓存（`_cached_agent_version`）；优先环境变量
  `CAREERCREW_AGENT_VERSION`（strip 后非空才用）；否则 `git rev-parse HEAD`
  （`subprocess.run`，cwd=项目根，timeout=2s）；任何失败 → `"unversioned"`。
- `prompt_version_for_agent(agent_id: str | None) -> str`：惰性 registry。
  - 6 个 agent_id（job_matcher / resume_advisor / career_planner / knowledge_advisor /
    interviewer / salary_negotiator）：惰性 import 对应模块，调用其 `prompt_source()`。
  - `interviewer_chat`：读 `careercrew_api/routers/interview.py` 的 `_CHAT_PROMPT_PATH`。
  - registry 未命中 → `"unversioned"`。
  - 惰性 import（函数内 import），模块加载期不拖入 langchain 等重依赖。

项目根路径用 `Path(__file__).resolve().parents[1]`（versioning.py 位于 careercrew_core/）。

### 6 个 agent 模块各加 `prompt_source()`

`{job_matcher,resume_advisor,career_planner,knowledge_advisor,interviewer,salary_negotiator}.py`
各加模块级函数：

```python
def prompt_source(prompt_path: Path | None = None) -> str:
    """返回本 agent 实际使用的 prompt 文本（与 __init__ 读取逻辑完全一致）。"""
    path = prompt_path or _PROMPT_PATH
    return path.read_text(encoding="utf-8") if path.exists() else _DEFAULT_PROMPT
```

与各自 `__init__` 的读取逻辑逐字一致（文件存在读文件，否则 `_DEFAULT_PROMPT`）。

### `careercrew_api/chat_lifecycle.py`

`begin_turn(...)` 新增关键字参数 `prompt_version: str = "unversioned"`、
`agent_version: str = "unversioned"`，替换原先硬编码的 `"unversioned"`：
- `start_run(...)` 传入 `prompt_version=prompt_version, agent_version=agent_version`。
- `TurnContext(...)` 携带 `prompt_version=prompt_version, agent_version=agent_version`。

### `careercrew_api/runtime.py`

`_begin_chat_turn(...)` 计算并传入：`prompt_version_for_agent(agent_id)` 与 `agent_version()`。
docstring 注明：编排类入口（consult_orchestrator 无单一 prompt）→ registry 未命中 →
unversioned，Phase 2/3 补编排级版本时再换。

### `careercrew_api/routers/interview.py`

`/chat`（对话式模拟面试）的 `_begin_chat_turn` 由 `agent_id="interviewer"` 改为
`agent_id="interviewer_chat"`，使该入口的 prompt_version 反映其实际使用的
`interviewer_chat.txt`（`new_interviewer(prompt_path=_CHAT_PROMPT_PATH)`），
与 `/questions`（默认 interviewer.txt）区分。

### `tests/api/conftest.py`（FakeRuntime）

FakeRuntime._begin_chat_turn 同样用真实 versioning 计算（brief 要求 "FakeRuntime 路径
用真实 versioning 计算"）。

## TDD 证据

### RED

- 先写 `tests/unit/test_versioning.py`：初次运行 `ImportError: cannot import name
  'versioning' from 'careercrew_core'`（模块不存在）—— RED。
- `tests/api/test_stable_ids.py` 原断言 `prompt_version == "unversioned"` /
  `agent_version == "unversioned"`，接线后会变绿为 sha256/git-sha —— 该断言在实现前为
  红（FakeRuntime 尚未接线版本）。

### GREEN

- `tests/unit/test_versioning.py`：13 passed（格式、确定性、不同输入、空/unversioned、
  env 注入、git 失败、缓存、绝不 unknown、registry 7 键、与 prompt 文件 sha256 一致、
  未知 agent unversioned）。
- `tests/unit/test_chat_lifecycle.py`：新增 1 项（begin_turn 版本传至 run 行与 TurnContext）。
- `tests/api/test_stable_ids.py`：新增/改造 3 项（6 端点 prompt_version 为 sha256、consult
  unversioned、interview/chat 用 interviewer_chat 版本）+ 原 `_assert_done_sect9` 改为
  sha256/git-sha 断言。
- 全量（POSTGRES_TEST_DSN=…/careercrew_test）：**579 passed**（基线 562 + 17 新增）。

## 实现期间发现的问题

1. **项目根路径 off-by-one**：`careercrew_core/versioning.py` 用 `parents[1]`（非 `parents[2]`）。
   初版误用 `parents[2]`（指向 `F:\agent_develop`），git cwd 与测试 prompt 路径均错，
   测试 `test_registry_matches_prompt_file_sha256` FileNotFoundError 暴露并修复。

2. **模块级缓存跨用例污染**：`agent_version()` 的 `_cached_agent_version` 会被前序 API 测试
   预先置为真实 git sha，导致 `test_agent_version_env_var_wins` 全量跑时断言缓存为 None 失败。
   修复为 autouse fixture 每用例前后清缓存。

3. **interviewer_chat 接线歧义**：interview `/chat` 路由实际用 `_CHAT_PROMPT_PATH`
   （interviewer_chat.txt）但原 agent_id="interviewer"。若不改，`interviewer_chat` 键将成为
   死代码、改 interviewer_chat.txt 不会引起版本变化（违反验收标准 "改 prompt 文件 → 版本串
   变化"）。裁决：`/chat` 路由 agent_id 改为 "interviewer_chat"。**注意**：这会改变该入口
   run 行的 agent_id（interviewer → interviewer_chat），属语义对齐、非回归。

## registry 键清单（`prompt_version_for_agent` 命中的 key）

| agent_id | prompt 来源 |
|---|---|
| `job_matcher` | careercrew_ai/prompts/job_matcher.txt |
| `resume_advisor` | careercrew_ai/prompts/resume_advisor.txt |
| `career_planner` | careercrew_ai/prompts/career_planner.txt |
| `knowledge_advisor` | careercrew_ai/prompts/knowledge_advisor.txt |
| `interviewer` | careercrew_ai/prompts/interviewer.txt |
| `salary_negotiator` | careercrew_ai/prompts/salary_negotiator.txt |
| `interviewer_chat` | careercrew_ai/prompts/interviewer_chat.txt |

`consult_orchestrator` 未注册（编排无单一 prompt）→ unversioned。

## 文件清单

- 新增：`careercrew_core/versioning.py`、`tests/unit/test_versioning.py`
- 修改：6 个 agent 模块（各 +`prompt_source()`）、`careercrew_api/chat_lifecycle.py`、
  `careercrew_api/runtime.py`、`careercrew_api/routers/interview.py`（仅 `/chat` agent_id 一行）、
  `tests/api/conftest.py`、`tests/unit/test_chat_lifecycle.py`、`tests/api/test_stable_ids.py`

## 自审发现

- **完整性**：验收标准全部满足 —— done 事件与 agent_runs 行 prompt_version 为
  sha256:<64hex>（有 prompt 时）/ `unversioned`（编排）；agent_version 为 git sha /
  unversioned；无任何 `unknown` 版本字面量。
- **质量**：清除 `_REGISTRY_AGENTS` 上方的陈旧注释；docstring 说明 consult 编排 unversioned
  的 Phase 2/3 后续。
- **纪律（YAGNI）**：未加编排级版本（consult_orchestrator），保持 unversioned 并在注释说明；
  未引入缓存库/配置项，仅模块级变量。
- **测试卫生**：autouse cache-reset fixture 防跨用例污染；registry 测试直接对标 prompt 文件
  sha256（证明 "改文件 → 版本变化"）。
- **grep 树**：`careercrew_api/` 下仅 `routers/resume.py:137` 出现 `"unknown"`，是
  文档扩展名兜底 `doc_type = ext.lstrip(".") or "unknown"`（非版本值，与 T1.5 无关）。
  版本相关路径无任何 `"unknown"`。
- **staging 纪律**：工作树存在并行会话未提交改动（interview.py 的 RuntimeInitError/friendly_error
  重构等）。仅用 `git add -p` 精确暂存我的 interview.py 单行（agent_id 改动），其余 foreign
  改动保持未暂存。commit 前确认 staged 恰为 14 文件。

## 疑虑（DONE_WITH_CONCERNS 依据）

1. **interview `/chat` 路由 agent_id 语义变化**：由 `"interviewer"` → `"interviewer_chat"`，
   目的是让 prompt_version 准确反映实际 prompt。但这改变了该入口 agent_runs 行的 agent_id。
   若后续有按 agent_id=="interviewer" 聚合 `/chat` 与 `/questions` 的逻辑，需注意此拆分。
   属有意决策（见 §实现 4），非回归，但值得显式记录。

2. **phase 2/3 编排级版本未覆盖**：consult_orchestrator 仍为 `unversioned`（brief 允许，
   注释已说明）。前端不动（合规）。

3. **git rev-parse 依赖仓库根**：`agent_version()` 在非 git 目录（如部署解压产物无 .git）
   会降级 unversioned —— 符合 brief "任何失败 → unversioned"，但生产若靠 git sha 标识版本，
   需保证部署环境保留 .git 或注入 `CAREERCREW_AGENT_VERSION`。

## 测试小结

- `tests/unit/test_versioning.py`：13 passed
- `tests/unit/test_chat_lifecycle.py`：+1（共 12 passed）
- `tests/api/test_stable_ids.py`：+3（共 19 passed）
- 全量（含 POSTGRES_TEST_DSN）`uv run pytest`：**579 passed, 3 warnings**（基线 562）

## Fix Round (review findings)

### 变更

1. **Finding 1 — 失败不再永久缓存 `unversioned`**（`careercrew_core/versioning.py` `agent_version()`）：
   - 删除失败路径的 `_cached_agent_version = _UNVERSIONED`，失败直接 `return _UNVERSIONED`
     且不写缓存（缓存哨兵保持 `None`），后续调用会重试 git/env。
   - 只有成功解析（git SHA 或 env 值）才写缓存；env 优先级与 2s 超时 git 路径不变。

2. **Finding 2 — 缓存测试改为真正证明缓存**（`tests/unit/test_versioning.py`
   `test_agent_version_module_cache`）：monkeypatch `subprocess.run` 为 spy（计数），
   清缓存（复用手动置 None）、清除 env 覆盖，两次调用 `agent_version()`，
   断言返回值 == fake git 输出 == `"fake-git-sha-1234"` 且 spy 恰好调用 1 次。

### 测试命令与结果

- `uv run pytest tests/unit/test_versioning.py -q` → **13 passed**
- 全量：`$env:POSTGRES_TEST_DSN = .../careercrew_test; uv run pytest -q` → **579 passed**（与基线一致）

### 提交

- `6e7f253` fix(versioning): retry agent version resolution after transient failure and prove caching
