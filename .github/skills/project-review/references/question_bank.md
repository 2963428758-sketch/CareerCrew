# CareerCrew 复习题库

> v0.1 starter - 基于 DEV_SPEC 设计级内容。代码落地后补充代码级细节与更多题目。
> 题号格式 `{章}-{序}`，如 `2-03`。难度 ⭐（基础）/⭐⭐（进阶）/⭐⭐⭐（深度）。

---

## 第 1 章：项目全景与设计理念（8 题）

### 1-01 ⭐ CareerCrew 解决什么问题？跟单点求职工具有什么本质区别？
**参考答案**：长期陪跑用户整个求职周期（匹配/简历/面试/谈判/规划），区别于单点工具的是有长期记忆、能调真实招聘平台与工具、带人工闸门的多 agent 系统。

### 1-02 ⭐⭐ 为什么用"多智能体团队"形态而不是单个大模型一条龙？
**参考答案**：求职本就是不同专业分工（匹配/简历/面试/谈判/规划），多角色协同天然成立；单模型难兼顾各角色专业性与工具调用可控性；多 agent 可会诊、可独立评估。

### 1-03 ⭐⭐ "高 stakes 决策"这个判断怎么影响了架构设计？
**参考答案**：引出默认 HITL（投递/接 offer 等必确认）、记忆系统（避免重复犯错）、风险分级工具（requires_confirmation）。高 stakes 决策不允许全自动。

### 1-04 ⭐ CareerCrew 的分层架构是什么？依赖方向？
**参考答案**：careercrew_ai -> careercrew_core -> careercrew_api，单向依赖，core 只发事件不碰渲染，web/ 独立前端。

### 1-05 ⭐⭐ 项目复用了 MODULAR-RAG-MCP-SERVER 哪些能力？为什么不从头写？
**参考答案**：复用 Hybrid 检索+Rerank+MCP+llm_factory/trace/evaluator/BaseVectorStore。不重复造轮子，聚焦 CareerCrew 自己的核心创新（多 agent+记忆+HITL+工作流）。

### 1-06 ⭐ "教是最好的学"在项目里怎么体现？
**参考答案**：配套 Skill 体系（auto-coder/resume-writer/interview-prep/project-review/project-learner 等）覆盖全生命周期，边做边整理面试题与简历素材。

### 1-07 ⭐⭐ 求职周期闭环有哪几个阶段？
**参考答案**：意向->规划->匹配->简历->面试->谈判->投递(HITL)->跟踪->复盘->循环。9 阶段。

### 1-08 ⭐⭐⭐ 如果向面试官用一句话讲清技术深度，你会怎么说？
**参考答案**：开放题。考察表达主线能力。应覆盖：Hybrid 架构（LangGraph+手写ReAct）、三层记忆、HITL 闸门、RAG 复用+Milvus 扩展。

---

## 第 2 章：多 Agent 编排 - LangGraph supervisor（8 题）

### 2-01 ⭐ supervisor 节点和 agent 节点的职责怎么分？
**参考答案**：supervisor 只做路由（读 state->判断阶段->路由 agent/interrupt/end），不直接调工具；agent 节点内跑手写 ReAct，调工具产出结果后回 supervisor。

### 2-02 ⭐⭐ supervisor 的路由依据哪个 state 字段？路由逻辑写在哪？
**参考答案**：依据 stage + user_intent，写在 `careercrew_core/supervisor/router.py` 的 `route(state)`。

### 2-03 ⭐⭐ checkpointer 的作用是什么？持久化了哪些东西？
**参考答案**：SQLite checkpointer 持久化 thread 级短期状态（CareerCrewState：stage/messages/pending_action/agent_outputs 等），进程重启可恢复。区别于情景记忆（长期）。

### 2-04 ⭐⭐⭐ supervisor 怎么判断该结束还是继续路由？
**参考答案**：结束条件--用户目标达成/无待办阶段/用户主动结束。否则按 stage 流转继续路由。考察状态机终止条件设计。

### 2-05 ⭐ 多 agent 会诊（高级）解决什么问题？怎么实现？
**参考答案**：同一问题（如接不接 offer）多 agent 并行给意见再综合。用 LangGraph fan-out + join。

### 2-06 ⭐⭐ CareerCrewState 里为什么要单独存 pending_action？
**参考答案**：HITL 待确认动作需要跨节点传递，interrupt 暂停后恢复时要拿到待确认动作才能继续。

### 2-07 ⭐⭐ 求职阶段状态机有 9 个状态，状态转换由谁触发？
**参考答案**：可由用户驱动（用户说"开始面试"）或 agent 产出触发（匹配命中后自动进简历阶段）。supervisor 负责状态转换。

### 2-08 ⭐⭐⭐ 为什么用 LangGraph 而不是 AutoGen/CrewAI？
**参考答案**：LangGraph 擅长显式状态机与 interrupt（HITL 原生）、checkpointer 短期持久化；与手写 ReAct 互补。AutoGen/CrewAI 偏黑盒编排，可控性与可观测性弱。

---

## 第 3 章：Agent 内核 - 手写 ReAct（7 题）

### 3-01 ⭐ 手写 ReAct 的 while 循环每轮做哪几步？
**参考答案**：组装上下文 -> 调 LLM（带工具 schema）-> 解析有无 tool_call -> 有则执行工具回喂结果再循环 -> 无则视为最终答案 break。

### 3-02 ⭐⭐ 怎么判断 LLM 返回里有没有 tool_call？
**参考答案**：解析 LLM 返回的 tool_calls 字段（统一 function calling 格式），而非正则解析 "Action: xxx"。

### 3-03 ⭐ 轮次上限怎么设？超限怎么办？
**参考答案**：默认 max_iterations=10，超限抛可读错误，防死循环。

### 3-04 ⭐⭐ 每轮上下文怎么组装？
**参考答案**：每轮重新组装短期对话（state.messages）+ 按需检索的记忆（memory_search）+ 已执行工具结果。不靠隐式状态。写在 `context_builder.py`。

### 3-05 ⭐⭐⭐ 为什么不用 LangGraph 的 create_react_agent 黑盒，非要手写？
**参考答案**：可见循环保证工具推理过程透明、可控、可测试、可回放；每轮可 trace（thought/tool_call/tool_result）；便于实现高级特性（steering/follow-up/abort/parallel_safe）。

### 3-06 ⭐⭐ ReAct 每轮怎么 trace 记录？
**参考答案**：每轮迭代记录到 trace（thought/tool_call/tool_result），trace_type=agent_loop，供 Dashboard 回放。

### 3-07 ⭐⭐⭐ （高级）工具并行/串行策略怎么实现？
**参考答案**：工具声明 parallel_safe 配置，一轮内 parallel_safe=true 的独立工具并行执行，有依赖的串行。

---

## 第 4 章：记忆系统 - 三层（8 题）

### 4-01 ⭐ 三层记忆分别是什么？
**参考答案**：短期=Context Window(state.messages)；情景=append-only JSONL+parentId 树+Milvus 向量；长期=User Model 结构化 JSON。

### 4-02 ⭐⭐⭐ 情景记忆为什么用 append-only JSONL + parentId 树？
**参考答案**：append-only 保证可完整回放（历史不改）；parentId 树让会话成树，从任意叶子回溯到根=上下文。红利：黄金轨迹回放（轨迹级评估基础）。

### 4-03 ⭐⭐ 从叶子回溯到根重建上下文的算法？
**参考答案**：给定叶子 id，沿 parentId 链回溯到根，按时间序拼接即为上下文。O(深度)。

### 4-04 ⭐⭐ 情景记忆向量存哪个 collection？和知识库怎么隔离？
**参考答案**：careercrew_episodic。知识库用 careercrew_kb。collection 隔离避免污染与误检。

### 4-05 ⭐⭐ User Model 为什么用结构化 JSON 不用自由文本？
**参考答案**：字段约束保证可被 agent 程序化读取与过滤（匹配官按目标公司过滤、谈判师按薪资底线）。自由文本不可靠。通过 profile_update 工具结构化更新。

### 4-06 ⭐ 基础写入触发点有哪些？
**参考答案**：面试结束写 interview_qa、投递后写 application、拿 offer 写 offer、匹配命中写 job_match。

### 4-07 ⭐⭐⭐ compaction 怎么判断该压缩了？用 token 占比还是字符数？
**参考答案**：用模型真实 usage token 数（不用字符数/4 估算）。占比超阈值（默认 0.7）触发。

### 4-08 ⭐⭐⭐ compaction 的保留区和压缩区怎么划？怎么防丢？
**参考答案**：保留区最近 ~20K tokens 原封不动；压缩区分块总结->合并->写 JSONL compaction 条目带 firstKeptEntryId。高级方向 Pre-compaction Memory Flush：压缩前先静默跑一轮把重要信息写进长期记忆再压缩。

---

## 第 5 章：工具层与 MCP（6 题）

### 5-01 ⭐ MCP 工具和内部函数怎么统一注册？
**参考答案**：都注册成带 JSON schema 的 tool，统一字段（name/description/schema/source/requires_confirmation/parallel_safe）。agent 同一接口调用。写在 `tools/registry.py`。

### 5-02 ⭐⭐ agent 调工具时，MCP 工具和内部函数调用路径一样吗？
**参考答案**：一样。注册表屏蔽来源差异，agent 只认 schema。MCP 工具由 mcp_client 发现注册，内部函数直接注册。

### 5-03 ⭐⭐ requires_confirmation 怎么标记？触发后流程？
**参考答案**：工具声明 requires_confirmation=true。执行前检查，若 true 则抛 Interrupt 信号给 supervisor，走 HITL（暂停->人工确认/拒绝/修改->恢复）。

### 5-04 ⭐ rag_query 工具怎么封装 MODULAR-RAG 检索？
**参考答案**：内部函数工具，调 MODULAR-RAG HybridSearch（BM25+Dense+RRF+Rerank），返回结构化 Chunk 列表回喂 ReAct。

### 5-05 ⭐⭐ MVP 阶段投递用 mock，mock 和真实 MCP 怎么无缝替换？
**参考答案**：统一注册表抽象，mock_apply 和真实 MCP 工具实现同一 schema，N 阶段替换 mock 即可，agent 无感。

### 5-06 ⭐⭐⭐ （高级）自建求职者端 MCP 怎么做？
**参考答案**：仿 boss-zhipin-mcp，Playwright+CDP 实现投递/进度跟踪/面经采集，暴露为 MCP Server 注册进工具层。

---

## 第 6 章：向量库与 RAG 复用（7 题）

### 6-01 ⭐ 给 MODULAR-RAG 加 Milvus 后端，实现了哪些方法？
**参考答案**：BaseVectorStore 的 upsert/query/delete_by_metadata/get_by_ids。写在 `milvus_store.py`，VectorStoreFactory 注册 milvus 路由。

### 6-02 ⭐⭐ Milvus 的 Dense+Sparse 混合检索和 MODULAR-RAG 双路编码怎么配合？
**参考答案**：MODULAR-RAG 双路编码（Dense Embedding + Sparse BM25），Milvus 原生支持混合检索，契合。向量库层做融合。

### 6-03 ⭐⭐ milvus-lite 和 Docker 版 Milvus 怎么配置切换？
**参考答案**：settings.yaml 的 vector_store.backend: milvus_lite | milvus_docker | chroma，工厂路由，零代码切换。

### 6-04 ⭐ 为什么选 Milvus 不选 Chroma？又为什么保留 Chroma 兜底？
**参考答案**：Milvus 原生 Dense+Sparse 混合检索、milvus-lite 嵌入式零外部服务；Chroma 是 MODULAR-RAG 已有实现，兜底保证可用性与回退。

### 6-05 ⭐⭐ 知识库 collection 和情景记忆 collection 为什么隔离？
**参考答案**：避免知识库检索污染个人记忆检索；语义不同（静态知识 vs 个人事件）；可独立管理生命周期。

### 6-06 ⭐⭐⭐ Chroma 兜底启用时，和 Milvus 的数据怎么处理？
**参考答案**：兜底是独立后端，切换需重新 ingestion（或迁移工具，本项目 MVP 不做自动迁移）。考察候选人对数据一致性的认知。

### 6-07 ⭐⭐ 复用 MODULAR-RAG 的依赖方式是什么？
**参考答案**：本地 editable install（pip install -e ../MODULAR-RAG-MCP-SERVER），复用 llm_factory/trace/evaluator/BaseVectorStore。

---

## 第 7 章：HITL 与求职工作流（6 题）

### 7-01 ⭐ 哪些动作必须人工确认？
**参考答案**：投递(submit_application)、打招呼(send_greeting)、接 offer(accept_offer)、谈薪话术(salary_talk_script)。

### 7-02 ⭐⭐ LangGraph interrupt 的机制是什么？状态存哪？
**参考答案**：interrupt 暂停图执行，thread 状态存 checkpointer，等人工输入后恢复。pending_action 存 state。

### 7-03 ⭐⭐⭐ interrupt 恢复后怎么保证状态一致？
**参考答案**：checkpointer 持久化完整 thread state，恢复时重建；pending_action 决定恢复后走确认/拒绝/修改分支；结果写情景记忆。

### 7-04 ⭐⭐ 求职周期 9 阶段，阶段切换由谁触发？
**参考答案**：可由用户驱动或 agent 产出触发。supervisor 负责。如匹配命中后可自动进简历阶段。

### 7-05 ⭐⭐⭐ （高级）Delegate 三级授权是哪三级？和基础 HITL 什么关系？
**参考答案**：只读草稿（高风险：投递/接offer/谈薪，必确认）-> 代发待确认（中风险）-> 主动执行（低风险：搜职位/出题/草稿）。是基础 HITL 的细化。

### 7-06 ⭐⭐ 为什么默认 HITL，仅低风险自动化？
**参考答案**：求职高 stakes，默认 HITL 是护栏；仅低风险（搜职位/出题/出草稿）自动化平衡效率与安全。Loop Engineering 原则。

---

## 第 8 章：评估与可观测性（6 题）

### 8-01 ⭐ 答案级评估和业务级评估分别评估什么？
**参考答案**：答案级=单次产出质量（简历匹配度/面试题质量，复用 Ragas）；业务级=dogfood 效果（投递->面试转化率/面试通过率/拿 offer）。

### 8-02 ⭐⭐ 业务级评估的"转化率"数据从哪来？
**参考答案**：情景记忆中的 application/interview_qa/offer 事件统计。

### 8-03 ⭐⭐ 全链路 trace 复用了什么？扩展了哪些 trace_type？
**参考答案**：复用 MODULAR-RAG TraceContext+JSON Lines。扩展 agent_loop/hitl/memory_op/compaction（在 query/ingestion 基础上）。

### 8-04 ⭐ LangSmith 追踪怎么用？
**参考答案**：LangSmith 全链路追踪（LLM/工具/ReAct/HITL/RAG/记忆），默认脱敏上传，控制台查看；记忆指标含 memory_hit_rate / compaction 无损率。

### 8-05 ⭐⭐ Web 数据看板有哪几个 tab？
**参考答案**：画像（可编辑）/ 记忆（语义事实+情景事件浏览/删除）/ 记忆设置（全局开关 + 用户级 enabled/generate/use）。

### 8-06 ⭐⭐⭐ （高级）轨迹级评估怎么做？黄金轨迹回放利用了什么？
**参考答案**：路由准确率/工具调用 precision-recall/memory_hit_rate/ReAct 效率/Grounding/HITL 触发正确性/压缩无损性。LLM-as-judge + 黄金轨迹回放。回放利用 append-only 树（历史轨迹可完整重放比对）。

---

## 第 9 章：测试与工程质量（5 题）

### 9-01 ⭐ 测试金字塔怎么分？
**参考答案**：大量单元测试为基座（ReAct 循环/记忆读写/工具路由）+ 中量集成测试（supervisor+agent+工具+记忆协作）+ 少量 E2E（求职闭环关键流程）。

### 9-02 ⭐⭐ agent 行为评估测试有哪些特殊维度？
**参考答案**：路由准确率/工具调用 precision-recall/memory_hit_rate/HITL 触发正确性/ReAct 效率/Grounding。区别于普通函数测试。

### 9-03 ⭐⭐ 单元测试怎么隔离外部依赖？
**参考答案**：LLM/Milvus/MCP 真实调用一律 Fake/Mock（unittest.mock/pytest-mock），集成测试再开真实后端。

### 9-04 ⭐ E2E 测试覆盖哪些关键流程？
**参考答案**：match_resume 闭环（M1）/interview_sim/apply_hitl/dogfood_cycle。

### 9-05 ⭐⭐ 覆盖率目标是多少？
**参考答案**：单元测试核心逻辑 ≥ 80%；关键路径集成测试 100%；E2E 至少 4 个关键流程。
