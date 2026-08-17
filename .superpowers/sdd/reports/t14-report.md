# Task T1.4 Report — Agent Run 观测落地（tokens / retrievals / tool_calls / langsmith_run_id）

## 状态

DONE_WITH_CONCERNS（详见末尾「疑虑」）

## 实现内容

### 1. Agent 层观测（`careercrew_ai/agents/langchain_agent.py`）

- 新增 `UsageAccumulatorMiddleware`：`wrap_model_call` 从 `AIMessage.usage_metadata`
  累计 `input_tokens`/`output_tokens`（键名 `input_tokens`/`output_tokens`，容错缺失
  与异常值），`snapshot()` 返回累计快照。
- 新增 `ObservabilityMiddleware`：`wrap_tool_call` 计时（`time.perf_counter` 毫秒）并
  记录每个 tool call 的 `{name, args, duration_ms, error}`；异常记录 `错误文本` 后原样
  上抛（错误回喂仍由既有 `MaxIterationsMiddleware` 负责，观测层不吞）。
- `AgentResult` 新增字段 `input_tokens: int | None` / `output_tokens: int | None` /
  `tool_call_details: list[dict]`（默认 None/[]，**老字段契约不变**）。
- `build_agent` 恒装配两个观测中间件，并把实例挂在返回图的 `_observability` 属性；
  `run_agent` 读该属性填充 `AgentResult` 新字段。无 usage 时 tokens 静默为 None。

### 2. Lifecycle 扩展（`careercrew_api/chat_lifecycle.py`）

- `TurnContext` 新增 `langsmith_run_id: str | None`。
- `finish_turn(...)` 新增可选参数 `input_tokens/output_tokens/total_tokens/
  langsmith_run_id/retrievals/tool_calls`：收尾时写 run 的 tokens/langsmith_run_id，
  并批量写 `add_retrieval` / `add_tool_call` 行。
- 脱敏：`_redact_truncate`（`redact_secrets` + ≤200 字符截断）用于 query_text /
  output_summary / error_summary；`_redact_dict` 递归脱敏 tool call `input_redacted`
  （字符串叶子脱敏截断，保留结构与数值）。**不落完整正文 / 敏感正文**。

### 3. Runtime 接线（`careercrew_api/runtime.py` + 路由）

- 模块级 `_capture_langsmith_run_id()`：照 `traced_call`/`attach_run_metadata` 模式，
  tracing 关闭时返回 None。
- 模块级 `_observability_from_result(result)`：从 `AgentResult` 抽 tokens + tool_call
  明细（`tool_call_details` → tool_call 行；`error` → status=failed + error_type/error_summary）。
- 模块级 `_rag_query_retrievals(details)`：从 `tool_call_details` 里 `name=="rag_query"`
  的条目生成 retrieval 行（query_text=args.query 摘要；doc/chunk id 与 score 拿不到 → NULL，
  尽力而为）。
- 六个 impl：
  - **match/resume**：读 `cycle.job_matcher/_resume_advisor.last_result`；
  - **planner**：读 `agent.last_result`；
  - **knowledge.ask**：读 `agent.last_result`，retrieval 行来自 `_sink` 收集的 sources
    （doc/score 直接取，`used_in_final_context` = 是否在 `_cap_sources` capped 列表，
    chunk_id 无 → NULL）；
  - 三者均生成 rag_query retrieval 行（非 knowledge 的 agent tool detials）。
  - **consult 路由**：只写 `langsmith_run_id`（编排图无单一 AgentResult，per-tool/retrieval
    不落，见疑虑）。
  - **interview 路由（questions/chat）**：`_interview_obs` 从 `agent.last_result` 抽观测 +
    rag_query retrieval 行。
- 每个 traced impl 在 `attach_run_metadata` 后取 `ls_run_id`，收尾时透传。
- 失败/取消路径：不写 retrieval/tool（只在 `_finish_chat_turn` 成功路径落，与既有
  fail/cancel 语义一致）。

## TDD 证据（RED → GREEN）

| 测试 | RED | GREEN |
|---|---|---|
| `tests/unit/test_agent_observability.py`（8 例） | ImportError: ObservabilityMiddleware 不存在 | 8 passed |
| `tests/unit/test_chat_lifecycle.py` 新增 4 例 | TypeError: finish_turn() unexpected kwarg 'retrievals' / AttributeError langsmith_run_id | 11 passed |
| `tests/api/test_observability_api.py`（1 例） | —（新增，直接驱动假 agent 观测） | 1 passed |

全量：**558 passed, 0 failed, 0 skipped**（基线 545，+13 新增）。

## 工具调用 ↔ 迭代对齐策略

- `tool_call_details` 由 `ObservabilityMiddleware.wrap_tool_call` 单独累计，按**实际工具
  执行顺序**（时间序）记录，**不依赖** `iterations[].tool_calls` 的对齐。
- 选择依据：`iterations` 里的 `tool_calls` 来自 model 节点的 AIMessage（声明还尚未执行），
  且 stream 模式下 model/tools 节点分开 — 把「哪个迭代声明的调用」与「实际执行明细」对齐
  并不可靠（尤其 max_iterations 短路 / 工具异常回喂时 tool_calls 有 id 但 ToolMessage 回喂
  顺序不定）。因此 per-tool 明细独立记录（name/args/耗时/error），不做迭代级映射。
- 代价：无法回到「第 N 轮迭代的哪个工具」，但对观测目标（token/工具名/状态/耗时/错误类型）
  足够，且避免脆弱对齐。LangSmith 里有完整逐轮明细兜底。

## 脱敏实现细节

- 复用 `careercrew_core.memory.redaction.redact_secrets`（API key / 32+ 令牌 / password=
  / 手机号 / 邮箱 → `[REDACTED]`）。
- 截断上限 200 字符（`_OBSERVABILITY_TEXT_LIMIT`），超长加 `…`。
- 应用点（均经 lifecycle 层，**先脱敏后落库**）：retrieval `query_text_redacted`、
  tool_call `input_redacted`（递归字符串叶子）、`output_summary`、`error_summary`。
- 红action遵守：无完整 chunk 正文（knowledge retrieval 不落 `text`）；无完整工具输出
  （`output_summary` 由 impl 侧不外泄原文——非 knowledge agent 的 rag_query 工具输出不落，
  只落 args 摘要）。

## 文件清单（仅本次变更）

- `careercrew_ai/agents/langchain_agent.py`
- `careercrew_api/chat_lifecycle.py`
- `careercrew_api/runtime.py`
- `careercrew_api/routers/consult.py`
- `careercrew_api/routers/interview.py`
- `tests/fakes.py`（FakeChatModel._stream 补 usage_metadata 回传，使其行为贴近真实流式模型）
- `tests/api/conftest.py`（FakeRuntime._finish_chat_turn 透传观测字段 + 可选注入）
- `tests/unit/test_chat_lifecycle.py`
- `tests/unit/test_agent_observability.py`（新增）
- `tests/api/test_observability_api.py`（新增）

## 自审发现

- **关键实现缺口（已定位）**：流式模式下 LangChain agent 的 `wrap_model_call` 返回的
  `AIMessage` **剥离了 `usage_metadata`**（invoke 模式保留，stream 模式丢）。定位到根因：
  真实流式 LLM 在流末以 `AIMessageChunk(usage_metadata=...)` 回传计量，由 agent 聚合到最终
  AIMessage；本仓库 `FakeChatModel._stream` 原来不 emit usage chunk，故 tokens 恒为 None。
  修复：`tests/fakes.py` 让 fake 流末 emit usage chunk（贴近真实模型），生产路径无需改动。
  **这是测试替身行为问题，不是生产代码 bug** —— 真实 deepseek 等模型 streaming 会带 usage。
- `_observability_from_result` 的 `error_type` 初始表达式有运算符优先级隐患，已重构为显式
  if 分支。
- `input_redacted` 由 impl 侧传 `tool_call_details[].args`（原始 args），脱敏在
  `finish_turn` 的 `_redact_dict` 统一做（递归字符串叶子），与 output_summary 同一防线。

## 疑虑

1. **consult 编排无 per-tool/retrieval 观测**：`consult_orchestrator` 是 LangGraph 多 agent
   编排，产出的 `last_result` 不聚合各子 agent 的 `tool_call_details`（子 agent 由
   `new_consult_agent` 每次新建，`last_result` 不含在返回的 `consult_calls` 里）。当前只落
   langsmith_run_id；tokens/tool/retrieval 留给后续（Phase 2/3 可在 orchestrator 内显式聚合）。
   已按 brief「仅写已发生的」最小化处理，未越界。
2. **非 knowledge agent 的 rag_query retrieval 拿不到 doc/chunk id 与 score**：rag_query
   返回纯文本（`[1] (score=..) text`），工具结果无结构化 doc/chunk id。按要求「尽力而为」：
   只落 query_text_redacted=args.query，document/chunk/score 为 NULL。若需完整检索可观测，
   需在 `make_rag_query_tool` 的 sink 里结构化回传 source（超出本任务范围）。
3. **`total_tokens` 由 input+output 推算**：`usage_metadata` 累计时未单独累计
   `total_tokens`（可能含缓存读 token 与 input+output 不等）。当前 input+output 求和；若未来
   需精确 total 需在 UsageAccumulatorMiddleware 里单独累计 `total_tokens` 键（低优先级）。

## Fix Round (review findings)

变更：
- Finding 1 — `careercrew_api/chat_lifecycle.py`：新增 `_redact_value()` 递归脱敏辅助，`_redact_dict` 的 list 分支改为逐项调用 `_redact_value`，从而递归脱敏 list-of-dict 与 list-of-list（字符串叶子脱敏截断，非字符串非容器叶子原样保留）。测试：`tests/unit/test_chat_lifecycle.py::test_finish_turn_redacts_list_of_dict_inputs`（list 内嵌套 dict 含 secret 字符串断言脱敏，结构与非字符串叶子保留）。
- Finding 2 — `careercrew_ai/agents/langchain_agent.py`：`UsageAccumulatorMiddleware` 新增 `_seen` 标志，仅在观测到 usage 时置位；`snapshot()` 返回 `(None, None)` 当从未观测到 usage，否则返回累计 int（0 保持 0）。`run_agent` 映射改为直接赋值（None→None，0→0）。测试：`test_usage_middleware_snapshot_no_usage_is_none`、`test_usage_middleware_snapshot_preserves_zero`、`test_run_agent_zero_tokens_preserved`。

测试命令与结果：
- `uv run pytest tests/unit/test_agent_observability.py tests/unit/test_chat_lifecycle.py -q` → 23 passed
- `$env:POSTGRES_TEST_DSN = uv run python -c "import re;raw=open('.env',encoding='utf-8').read();print(re.search(r'^DATABASE_URL=(.+)$',raw,re.M).group(1).strip().rsplit('/',1)[0]+'/careercrew_test')"; uv run pytest -q` → 562 passed, 3 warnings（基线 558 + 4 新增）

Commit SHA: fc4a5f1
