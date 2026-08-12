# CareerCrew 项目知识库（面试评估依据）

> 面试官评估候选人回答时的参考标准。每模块含：核心要点、关键代码锚点、常见露馅点。
> v0.1 基于 DEV_SPEC 设计；代码落地后补充实现细节。

## 1. 多 Agent 编排（LangGraph supervisor）
- **核心要点**：supervisor 节点只做路由（读 state -> 判断阶段 -> 路由 agent / interrupt / end），不直接调工具；agent 节点内跑手写 ReAct；HITL 节点处理 interrupt；checkpointer(SQLite) 持久化 thread 短期状态。
- **关键锚点**：`careercrew_core/supervisor/graph.py`、`router.py`、`hitl.py`；`state/thread_state.py`（CareerCrewState）。
- **常见露馅点**：说不清 supervisor 和 agent 的职责边界；把 checkpointer 和情景记忆混为一谈；说不清路由依据哪个 state 字段。

## 2. Agent 内核（手写 ReAct）
- **核心要点**：可见 while 循环（组装上下文 -> 调 LLM -> 解析 tool_calls -> 执行工具 -> 结果回喂 -> 再循环）；无 tool_call 即结束；轮次上限防死循环；每轮 trace 记录 thought/tool_call/tool_result。
- **关键锚点**：`careercrew_ai/react/react_loop.py`、`context_builder.py`。
- **常见露馅点**：说不清怎么判断有无 tool_call（应答：解析 LLM 返回的 tool_calls 字段）；答不出轮次上限处理；误以为是 LangGraph create_react_agent 黑盒。

## 3. 记忆系统（3 层，仿 Hermes）
- **核心要点**：短期=Context Window(state.messages)；情景=append-only JSONL + parentId 树 + Milvus 向量，从叶子回溯到根重建上下文；长期=User Model 结构化 JSON。基础写入触发点：面试/投递/offer/匹配后写。compaction 基础版：token 占比触发（用模型真实 usage）+ 保留区 + 压缩区 + firstKeptEntryId。
- **关键锚点**：`careercrew_core/memory/episodic.py`、`user_model.py`、`compaction.py`、`vector_index.py`。
- **常见露馅点**：说不清 append-only 树的红利（黄金轨迹回放）；答不出从叶子到根的回溯算法；把情景记忆和长期记忆混淆；compaction 用字符数/4 估算 token（应答：用模型真实 usage）。

## 4. 工具层与 MCP
- **核心要点**：统一工具注册表，MCP 工具（mcp-jobs/Google MCP）+ 内部函数（rag_query/memory_search/memory_write/profile_update）都注册成带 schema 的 tool，agent 同一接口；requires_confirmation 标记高风险工具触发 Interrupt。
- **关键锚点**：`careercrew_core/tools/registry.py`、`internal/*`、`mcp/mcp_client.py`。
- **常见露馅点**：说不清 MCP 工具和内部函数如何统一接口；答不出高风险工具的拦截流程。

## 5. 向量库与 RAG 复用
- **核心要点**：复用 MODULAR-RAG（Hybrid BM25+Dense+RRF + 两段式 Rerank + MCP + llm_factory/trace/evaluator）；给 BaseVectorStore 扩 Milvus 后端（实现 upsert/query/delete_by_metadata/get_by_ids，支持 Dense+Sparse）；milvus-lite 本地嵌入式 + Docker 演示 + Chroma 兜底，配置切换；collection 隔离（careercrew_kb 知识库 / careercrew_episodic 情景记忆）。
- **关键锚点**：`MODULAR-RAG-MCP-SERVER/src/libs/vector_store/milvus_store.py`；`config/settings.yaml` 的 vector_store.backend。
- **常见露馅点**：说不清为什么要扩 Milvus（应答：Dense+Sparse 混合检索、本地嵌入式零外部服务）；答不出 collection 隔离原因；误以为 Chroma 和 Milvus 共用数据。

## 6. HITL 闸门
- **核心要点**：默认 HITL（高 stakes 决策）；投递/打招呼/接 offer/谈薪话术必确认（LangGraph interrupt）；恢复可确认/拒绝/修改；高级方向 Delegate 三级授权（只读草稿/代发待确认/主动执行）。
- **关键锚点**：`careercrew_core/supervisor/hitl.py`。
- **常见露馅点**：说不清 interrupt 后状态存哪、怎么恢复一致；答不出哪些动作必确认。

## 7. 求职周期工作流
- **核心要点**：9 阶段闭环（意向->规划->匹配->简历->面试->谈判->投递[HITL]->跟踪->复盘->循环）；supervisor 路由；阶段切换可由用户驱动或 agent 产出触发；拿 offer 即 dogfood 验收。
- **关键锚点**：`careercrew_core/workflow/job_cycle.py`。
- **常见露馅点**：答不出阶段顺序；说不清哪些阶段必 HITL。

## 8. 评估与可观测性
- **核心要点**：LangSmith 全链路追踪（脱敏上传，控制台查看）；Web 数据看板（画像/记忆/记忆设置）；答案级评估（简历匹配度/面试题质量，复用 Ragas）+ 业务级（转化率/通过率/offer，数据来自情景记忆事件统计）；高级方向轨迹级评估（LLM-as-judge + 黄金回放）。
- **关键锚点**：`careercrew_core/evaluation/`、`careercrew_web/src/pages/DataPage.tsx`。
- **常见露馅点**：把答案级和业务级评估混为一谈；答不出业务级评估数据来源；说不清 LangSmith 脱敏与记忆指标。

## 9. 分层架构与本地优先
- **核心要点**：三层单向依赖（careercrew_ai -> careercrew_core -> careercrew_api），web 前端独立；本地优先（Postgres/Qdrant 本地 Docker，LLM/Rerank 走 API）；LLM 可插拔复用 llm_factory。
- **关键锚点**：`docs/DEV_SPEC.md` §3.12、§5.2 目录树。
- **常见露馅点**：答不清依赖方向；说不清本地优先的具体体现。
