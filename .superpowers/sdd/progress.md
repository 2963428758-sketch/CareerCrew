plan: docs/superpowers/plans/2026-08-15-multiuser-auth-knowledge.md

Task A1: complete (commit 29db20f, 20/20 config tests)
Task A2: complete (commit HEAD, 8/8 unit + 1/1 postgres integration)

Task A3: complete (11/11 unit)

Task A4: complete (9/9 auth api)

Task A5: complete (11/11)

Task A6: complete (4/4 unit + 1/1 pg integration)

Task B1: complete (23/23 vector store tests)

Task B2+B3: complete (27 knowledge api + visibility matrix green)

Task B4: complete (16/16 migration tests)

Task B4 live: careercrew_mm 211 点迁移完成（changed=211→rerun 0/211 skip），episodic 未动；langchain_v1_tools 4 点迁移前已被删除（原始文件仍在）

Task D1: complete (fetch_kb/ingest reworked, data/knowledge archived, OPS_BACKUP.md added)

Task D2: complete (backend 437 passed incl. integration; frontend 14/14 + lint 0 + build ok; live PG auth smoke ok)

FIX login: integration tests had wiped prod auth_accounts; restored u_001/liyou from sqlite backup, added disposable-db guard + careercrew_test

---

# plan2: docs/CareerCrew_Agent_Feedback_Eval_Detailed_Plan.md

branch: feature/agent-feedback-eval (baseline 7784701, merge-base d348087)
scope: Phase 0-6（Phase 7 按方案 §45 前提暂缓）
backend baseline: 437 passed (`uv run pytest`)

Task T0.1: complete (commits 3aad437 + f0c6f1f, review clean; 439 passed)
  → final review 待办(Minor): 前端 ROLE_LABEL 缺 quality_reviewer 文案（Phase 5 补）；
    test_auth_api.py 有冗余 dependency 直接调用断言；迁移幂等测试混入角色功能断言

Task T0.2: complete (commits 64d1156 + 0374ea3, review clean; 451 passed)
  真实 dry-run: scanned=225（careercrew_mm 211 + episodic_v2 14），unowned=0，无需 apply；
  方案文档 "232" 确认为过时估算。
  → final review 待办(Minor): except Exception 吞 set_payload 失败无告警；报告旧正文描述 stale；
    scan 全量内存物化；COLLECTION_KEY_FIELD 常量与 resolve_collections 双映射易漂移

Task T0.3: complete (commits 8c632fd + e24bd08, review clean; 470 passed + 8 skipped)
  12 隔离测试 + 7 真实 store 所有权测试；未发现越权漏洞（线程/记忆/知识所有权已正确）。
  → final review 待办(Minor): 无 RED 阶段（基线已绿）；FakeRuntime 与真实 store 双层覆盖已并存

# Phase 0 完成：quality_reviewer 角色 ✅ / Qdrant 迁移校验 ✅（unowned=0）/ 跨用户隔离 ✅
# 注意：force relogin 已由前一轮 accounts→PG 迁移自然完成（旧 refresh token 未迁移），无需新动作。

# ── Phase 1：稳定 Message / Run ──

Task T1.1: complete (commits 967639e + 843dc53 + b57d868, review clean; 513 passed 0 skipped)
  careercrew_core/conversation/：6 表 + UUIDv7 + legacy_thread_id 映射 + OwnershipError。
  关键决策（已定，供后续任务引用）：user_id 列 VARCHAR(64)（方案 DDL 的 UUID 与
  现有 u_001 账号体系矛盾，按方案 §5.2 保留账号 ID 原样）。
  POSTGRES_TEST_DSN 一键：见 briefs/t11 修复轮命令（.env 派生 careercrow_test）。
  → final review 待办(Minor): add_user_message 未校验 turn_id 属于 thread；读查询包事务；list_message_versions O(n)。

Task T1.2: complete (commits 8f60df4 bcecb1a b96f794 8778dd1 2382319 21211a1, review clean; 539 passed)
  6 个流式入口全部接入 conversation 记录 + done 事件 §9 字段；threads 路由（POST 统一
  兼容旧注册语义；GET messages 所有权 404）；legacy 映射稳定。
  裁决：resume 模块 conversation=resume（canonical）/ episodic=matcher（legacy 不改）。
  → final review 待办(Minor): _fail/_cancel 静默吞 conversation 写异常（有意为之，待注释强化）；
    failed 消息 completed_at=NULL；knowledge docstring 旧返回形态描述。

Task T1.3: complete (commits a52620b edc967d b2212f9, review clean; backend 545 / frontend 31)
  裁决（controller）：消息 shape 用独立 messageId/turnId/runId 字段（id 保留为 UI key/anchor）✅。
  修复轮：remap 重挂 controllers/thinkTimers、恢复 Interview 评分、ConsultCall 类型对齐。
  → final review 待办(Minor): types.ts ConsultCall 注释措辞过强；nextId 计数器跨页面增长。

Task T1.4: complete (commits 3cbe513 f2ed246 fc4a5f1, review clean; 562 passed)
  Usage/Observability 双中间件；finish_turn 批量写 retrievals/tool_calls（红action+截断）；
  consult 仅 langsmith_run_id（编排无聚合 AgentResult，Phase 2/3 再补）；rag_query 的
  doc/chunk id 尽力而为（NULL）。
  → final review 待办(Minor): total_tokens=input+output 推算（缓存读 token 失真）；
    error_type 解析脆弱；_seen 在转换前置位（畸形 usage 计为 0）。

Task T1.5: complete (commits 5185788 6e7f253, review clean; 579 passed)
  careercrew_core/versioning.py：sha256:<hex> prompt 版本 + git-sha agent 版本；
  interviewer /chat 拆为 interviewer_chat（更准的 prompt 溯源）；consult 维持 unversioned。
  → final review 待办(Minor): salary_negotiator 无顶层 turn 路径；agent_version 未做
    40-hex 校验；registry if-chain 可用 importlib。

Task T1.6: complete (commits 0a28ef6 b0ed935 47ef2e7 69ed84d, review clean after 2 fix rounds; 617 passed)
  regenerate：turn 不变/新 run+message/regenerated_from 链；thread-last 守卫；幂等键
  三态预留（reserved/exists+id/exists+None→409 进行中）；resume 缺 jd_text→409；
  consult/interview MVP 409。
  注意：T1.6 首次实现者死亡（无提交），续作代理接管并提交；并行会话的
  display_name/错误本地化 hunk 均完整保留。
  → final review 待办(Minor): store.reserve 包装器丢 message_id 参数；
    created_at 字符串比较脆弱；生成中重放(存在+None)语义 409 已实现。

# ── Phase 1 完成 ── 稳定 Message/Run：conversations 表 ✅ done 事件 ✅ 前端恢复 ✅
#   观测 ✅ 版本溯源 ✅ regenerate ✅（后端 617 / 前端 31 全绿）

# ── Phase 2：会话 UX ──

Task T2.1: complete (commits 1ab9c8f 200fdb0, core review clean; frontend 52 tests)
  ⚠️ 6 页挂载接线仍**未提交**（与并行会话 ConversationHeader 重构行级交织；
  备份 .superpowers/sdd/deferred/t21-page-wiring.patch）。核心引擎自洽：单文本域计数+高亮、
  作用域 Ctrl+F/Esc。→ final review 待办(Minor): 跨节点拆分关键词匹配为 0。

Task T2.2: complete (commits e1389d7 ecfd4ff, review clean; frontend 68 tests)
  Rail + useActiveTurn 测试全覆盖（IO 穿越重算、EdgeTick 精确跳转、settle 几何公式）。

Task T2.3: complete (commits bb1c10f 5b30449 788673b, review clean; backend 648 / frontend 78)
  rename/export(md+json 白名单+敏感串哨兵)/clear/delete + 前端 ConversationMenu；
  legacy-only delete 回退修复；regeneration_keys 清理；旧线程 export→404（已批准）。
  ⚠️ 菜单接线仍**未提交**（备份 .superpowers/sdd/deferred/t23-header-wiring.md）。
  → final review 待办(Minor): delete_conversation 嵌套事务；敏感串哨兵可能误报。

Task T2.4: complete (commits 534de0d b9e0a28, review clean; frontend 94 tests)
  streamStore.regenerate + VersionSwitcher（内联消息+turnId 分组=最新）+ §17 gating。
  ⚠️ ChatPage 接线**未提交**（备份 .superpowers/sdd/deferred/t24-chatpage-wiring.md）。
  → final review 待办(Minor): User Message 侧 action bar 未实现；copy 测试注释措辞。

# ── Phase 2 完成 ── 搜索 ✅ Rail ✅ 菜单/导出 ✅ Regenerate UI ✅（三处接线 deferred）

# ── Phase 3：Composer 能力 ──

Task T3.1: complete (commits c07c997 4ba55ce, review clean; ~710 passed)
  chat_attachments 表 + 校验（扩展名/MIME/magic/25MB）+ 上传/列表/删除/下载 +
  TTL 7 天清理脚本 + save-to-knowledge 501 占位（T3.2+T3.3 接真）。
  每 turn 5 文件限制暂按 per-thread 累计（broad reading，已记录）。
  → final review 待办(Minor): _synchronized 单连接注释失实（每操作新连接）；
    content_head 校验切片语义；同用户跨线程附件直查未单测。

Task T3.2+T3.3: complete (commits e376fe3 c4a3fc4 c520f44, review clean; 717 backend / 112 frontend)
  save-to-knowledge：category 自动分类、parsing→saved/failed 状态机（ready 仅保留枚举）、
  parser_error 成功即清；前端 AttachmentPicker（chips/删除/存库/重试）+ lib。
  ⚠️ ChatPage 接线**未提交**（deferred，同并行会话规则）。
  → final review 待办(Minor): 成功路径 mark_saved+update_status 双写略冗余。

Task T3.4: complete (commits d48a654 9c68182 8f449f7, review clean; 739 backend / 122 frontend)
  context resources API + mentions 重校验（不信任客户端 id）+ retrieval_source 列
  （mention/auto）+ knowledge.ask 强制上下文（访问约束进 must，防纵深）；
  resume mention 记录不注入；其他模块记录到 user metadata。
  ⚠️ MentionPicker 页面接线**未提交**（deferred）。
  → final review 待办(Minor): resume /generate /chat 请求无 mentions（后续）；
    Fake 的 resolve_mentions 与生产谓词可能漂移；types 映射有损。

Task T3.5: complete (commits 4157758 c687fb4 e8f1e33 204b67c 3023020, final review clean; 33 focused backend tests)
  Tool capabilities/effective intersection/HITL MVP complete. Final review verified a real matcher-bound
  submit_application tool is blocked and recorded awaiting_confirmation; consult now persists only its
  advisors' actual tool union. Frontend ToolPicker remains page-wiring deferred with the other composer UI work.

# ── Phase 4：Feedback ──

Task T4.1: complete (commits 40a7fd4 71039af b1dbfcd, final review clean; 31 focused tests + 14 PG skips)
  Feedback persistence/API, 90-day authorized snapshots, shared pre-truncation redaction, atomic consent
  revocation/audit, and ownership-safe restore are complete. Postgres integration coverage is present but requires
  POSTGRES_TEST_DSN to execute. Frontend API wiring and persisted feedback restoration remain T4.2.

Task T4.2: complete (commits bc7f5c1 eb33e79 324ac3d 7378495, final review clean; 30 clean-snapshot frontend tests)
  Persisted feedback UI, explicit per-open consent, stale-hydration protection, regenerate version separation, and
  six-module stable-ID wiring complete. Scoped toast/error prerequisites are committed. Full frontend build is blocked
  by pre-existing out-of-scope ConversationHeader/page errors, independently confirmed in clean snapshot.

# ── Phase 5：质量看板 + Phase 6：Eval 数据集（T5.x + 收尾） ──

Task T5.1: complete (review clean; metrics 聚合/过滤/版本趋势见 T5.2 提交)
  质量指标汇总路由规划；后端结构确认（bad-cases 独立快照存储 + 统一质量看板）。

Task T5.2+T5.5: complete (commit c92bfb6 "feat(quality): add dashboard metrics API with unversioned-run alert", 5 files, 315 insertions)
  /api/quality/metrics 聚合（feedback_coverage/route_accuracy/citation_coverage/tool_success/consult 延迟与 token 均值，
  均四舍五入 4 位）；/bad-cases 列表（根因分类+status+session_context 脱敏）；/reviews/{id} 根因+备注归因；
  /snapshots/{id} 90 天授权脱敏快照；/diagnostics/turn/{id} 回溯；unversioned run 告警（bad_cases_missing_version）。
  测试：tests/api/test_quality_metrics_api.py 22 断言 + PG 集成测试（feedback_coverage 用 approx abs=0.001）。
  → 踩坑：FastAPI 返回 str 时 TestClient.text 是 JSON 字符串需 .json()；start_run 默认 agent_version=unversioned
    全版本化测试须显式传参；finish_run 而非 update_run。

Task T5.4: complete (commit 55b5731 "feat(quality): promote bad cases to eval dataset with approval and export", 7 files, 659 insertions)
  eval_cases 表（source_feedback_id 级联、rubric JSONB、approved_at）+ CRUD（PG 事务内写 audit，Fake 同步）；
  POST /bad-cases/{id}/promote（负反馈+share_context+未过期快照校验→draft）；PUT approve 需 expected_behavior+rubric；
  approved→deprecated 允许降级；GET /eval-cases/export JSONL（路由声明在 /{case_id} 之前）；
  scripts/export_eval_dataset.py（PG→evals/careercrew/<version>/cases.jsonl）；eval_runner --bad-cases + RELEASE_GATE 门禁
  （bad_case_pass_rate 降>2%、route_accuracy>1%、citation_coverage>3%、tool_success>1%、延迟/Token 升>20%/25%）；
  冒烟：bad_case_pass_rate=0.0 → --compare --fail-on-regression exit=1。
  测试：tests/api/test_quality_eval_cases_api.py 全生命周期+护栏；PG 集成覆盖审计写表。

Phase 6 前端: complete (build exit=0; vitest 150 tests / 31 files)
  lib/quality.ts 类型+端点封装；QualityDashboardPage（指标卡/原因分布/版本趋势/unversioned 横幅）；
  BadCasesPage（状态筛选+计数）；BadCaseDetailPage（元数据/根因+备注归因/promote/脱敏快照查看）；
  EvalCasesPage（筛选/编辑 expected_behavior+rubric/批准/弃用/导出）；App.tsx 路由+角色门控
  （/quality* 需 quality_reviewer，PAGES 精确匹配 + QUALITY_BAD_CASE_DETAIL 正则）；AppSidebar NAV reviewerOnly 过滤。
  → 已知缺口：CreateUserDialog/UserManagementPanel 仅 admin/user 两角色，无法从 UI 建 quality_reviewer（并行文件，未动）。

后端全量回归: 769 passed in 113.07s (tests/api tests/unit, exit=0)
  修复 pre-existing 挂起 bug：test_auth_api 卡死根因＝lifespan 裸调 get_auth_service() 绕过 dependency_overrides，
  PostgresAccountStore.__init__ 急切 psycopg.connect 到不可达库 → 改惰性连接（_ensure() 线程锁 + _connected 标志）。

收尾 deferred 接线: complete（本提交）
  ChatPage：ConversationMenu（header extra，清空后 restoreHistory）+ AttachmentPicker/MentionPicker/ToolPicker
  （PromptComposer attachments/mentions/tools defer 槽位，streaming 时 disabled，AttachmentPicker 绑定当前 threadId）。
  其余 5 模块页（matcher/interview/resume/knowledge/consult）同模式接入 ConversationMenu。
