# CareerCrew 项目技术亮点（简历素材）

> 10 大亮点，每条含：核心说法、话术方向、量化角度、对应代码/文档锚点。
> 代码级细节待实现后补充（v0.1 基于 DEV_SPEC 设计）。

## 亮点 1：多智能体协同（5 Agent 团队 + Supervisor 路由）
- **核心说法**：设计"职业顾问团队"，5 个专职 agent（职位匹配官/简历顾问/面试官/薪资谈判师/职业规划师）由 LangGraph supervisor 按求职阶段路由调度。
- **话术方向**：多角色协同天然成立（求职本就是不同专业分工）；supervisor 状态机显式化、路由可解释可测试；支持多 agent 会诊（高级）。
- **量化角度**：5 个 agent、9 个求职阶段状态、路由准确率（golden 集）。
- **锚点**：`docs/DEV_SPEC.md` §3.1、`careercrew_core/supervisor/`、`careercrew_core/agents/`。

## 亮点 2：Hybrid Agent 架构（LangGraph 编排 + 手写 ReAct 内核）
- **核心说法**：LangGraph supervisor 管编排与 HITL/checkpointer，agent 节点内套可见的 while ReAct 循环，不依赖 agent 黑盒。
- **话术方向**：分工必然性（LangGraph 擅长状态机与中断，手写循环擅長工具推理细节与可控性）；每轮迭代可观测、可测试、可回放。
- **量化角度**：ReAct 轮次上限、工具调用 precision/recall、trace 全链路。
- **锚点**：`docs/DEV_SPEC.md` §3.2、`careercrew_ai/react/react_loop.py`。

## 亮点 3：三层记忆系统（仿 Hermes）
- **核心说法**：短期(Context Window) / 情景(append-only JSONL + parentId 树 + Milvus 向量) / 长期(User Model 结构化)，append-only 树支持历史轨迹完整回放。
- **话术方向**：append-only 树的红利（黄金轨迹回放、轨迹级评估）；从叶子回溯到根重建上下文；compaction 基础版（保留区+压缩区）。
- **量化角度**：3 层、记忆利用率(memory_hit_rate)、压缩无损性。
- **锚点**：`docs/DEV_SPEC.md` §3.3、`careercrew_core/memory/`。

## 亮点 4：RAG 后端复用 + Milvus 可插拔
- **核心说法**：复用 MODULAR-RAG-MCP-SERVER（Hybrid BM25+Dense+RRF + 两段式 Rerank + MCP），给其 VectorStore 抽象基类加 Milvus 后端，Chroma 兜底，配置切换。
- **话术方向**：不重复造轮子（复用 llm_factory/trace/evaluator）；扩 Milvus 是真贡献（Dense+Sparse 混合检索）；本地 milvus-lite 嵌入式零外部服务。
- **量化角度**：Hit Rate@10 ≥ 90%、MRR ≥ 0.8、检索延迟。
- **锚点**：`docs/DEV_SPEC.md` §3.5/§3.7、`MODULAR-RAG-MCP-SERVER/src/libs/vector_store/milvus_store.py`。

## 亮点 5：Function calling 统一工具层
- **核心说法**：MCP 工具（mcp-jobs/Google MCP）+ 内部函数（memory_search/profile_update/rag_query 等）都注册成带 schema 的 tool，agent 同一接口调用，高风险工具标 requires_confirmation。
- **话术方向**：统一接口屏蔽工具来源差异；风险分级触发 HITL；工具可观测（每次调用入 trace）。
- **量化角度**：6+ 工具、统一 schema、HITL 触发正确性。
- **锚点**：`docs/DEV_SPEC.md` §3.4、`careercrew_core/tools/registry.py`。

## 亮点 6：HITL 人工闸门（高 stakes 决策）
- **核心说法**：求职是高 stakes 决策，默认 HITL；投递/打招呼/接 offer/谈薪话术必确认（LangGraph interrupt）；高级方向 Delegate 三级授权。
- **话术方向**：高 stakes 场景的工程化护栏；interrupt 暂停-恢复状态一致性；默认 HITL 仅低风险自动化（Loop Engineering 原则）。
- **量化角度**：4 类必确认动作、HITL 触发正确性、Delegate 三级。
- **锚点**：`docs/DEV_SPEC.md` §3.8、`careercrew_core/supervisor/hitl.py`。

## 亮点 7：求职周期工作流闭环（dogfood）
- **核心说法**：意向->规划->匹配->简历->面试->谈判->投递(HITL)->跟踪->复盘->循环，完整可 dogfood 的求职陪跑闭环。
- **话术方向**：闭环思维（不是单点工具）；拿 offer 即项目验收；用自身知识库 dogfood。
- **量化角度**：9 阶段闭环、投递->面试转化率、面试通过率、拿 offer。
- **锚点**：`docs/DEV_SPEC.md` §3.9、`careercrew_core/workflow/job_cycle.py`。

## 亮点 8：全链路可观测 + 评估闭环
- **核心说法**：LangSmith 全链路追踪（脱敏上传）+ Web 数据看板（画像/记忆/记忆设置）；答案级评估（简历匹配度/面试题质量，复用 Ragas）+ 业务级评估（转化率/通过率/offer）。
- **话术方向**：agent 系统的黑盒问题用 LangSmith trace 破解；轨迹级评估（高级，LLM-as-judge + 黄金回放）。
- **量化角度**：LLM/工具/ReAct/HITL/RAG/记忆全链路追踪、答案级+业务级双维度。
- **锚点**：`docs/DEV_SPEC.md` §3.10/§3.11、`careercrew_web/src/pages/DataPage.tsx`。

## 亮点 9：本地优先（零外部服务）
- **核心说法**：Postgres/Qdrant 跑在本地 Docker（通用容器，跨项目共用），LLM/Rerank 走硅基流动 API，`pip install` 即可跑通。
- **话术方向**：本地优先设计哲学；基础设施与项目解耦（Docker 通用容器）。
- **量化角度**：Postgres 统一记忆 + Qdrant dense+sparse 向量 + LangSmith 追踪。
- **锚点**：`docs/DEV_SPEC.md` §2、`config/settings.yaml`。

## 亮点 10：Skill 驱动全流程（差异化亮点）
- **核心说法**：配套 auto-coder / resume-writer / interview-prep / project-review / project-learner / package / skill-creator 等 Skill，覆盖编码/测试/复习/面试/简历/打包全生命周期，"教是最好的学"。
- **话术方向**：AI 工程化方法论（spec 驱动自动开发：同步 spec->找任务->实现->测试->持久化）；全流程自动化；spec 驱动保证代码与设计一致。
- **量化角度**：7+ Skill、61 个子任务可自动推进、DEV_SPEC 单一事实源。
- **锚点**：`.github/skills/`、`docs/DEV_SPEC.md` §6 排期。
