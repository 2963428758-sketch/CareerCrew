# 生成 CareerCrew DEV_SPEC 初稿的 prompt（v3）

我想写一份完整的开发规范文档（DEV_SPEC），用于指导 CareerCrew（多智能体求职顾问系统）项目的全部开发流程。请帮我生成框架和初步内容。**重要：技术方向分"MVP 核心(必须实现)"和"高级方向(理解/能讲/后期实现)"两层,spec 要清晰区分,不要把高级内容当作必做。**

## 项目是什么

我要做一个多智能体"职业顾问团队"系统 CareerCrew，**长期陪跑用户整个求职周期**：职位匹配、简历定制、面试模拟、薪资谈判、职业规划。区别于单点工具,它是一个**有长期记忆、能调用真实招聘平台与工具、带人工闸门**的多 agent 系统。Demo 入口以 CLI 优先（本地优先、轻量、零外部服务依赖），后续加 Streamlit 展示页。

## 项目定位与特色

面向学习和面试求职的实战项目："教是最好的学"（边做边录视频,架构清晰易讲解）；配套文档/代码/视频,每模块整理面试高频题和简历建议；开箱即用且支持深度扩展,可作简历项目。立意:求职是高 stakes 生活决策,多角色协同天然成立,技术栈每项都有必然性,知识库现成能自己 dogfood。

## 已有的技术方向

### 【A. MVP 核心 - 必须实现】

1. **多 Agent 编排（LangGraph supervisor）**：5 个 agent（职位匹配官/简历顾问/面试官/薪资谈判师/职业规划师）；LangGraph supervisor 按求职阶段路由,支持多 agent 会诊；interrupt 做 HITL；checkpointer(SQLite) 做短期 thread 状态持久化。

2. **记忆系统（基础版,3 层）**：短期=Context Window；情景=Session Transcript（append-only JSONL,每条带 id+parentId,会话存成树,从叶子回溯到根=上下文）+ Milvus 向量；长期=User Model（能力画像/目标公司池/偏好,结构化）。基础写入(面试/投递/offer 后写情景记忆)+ 重建上下文。

3. **手写 ReAct 循环（基础版）**：套在 LangGraph agent 节点内,可见的 while 循环（组装上下文 -> 调模型 -> 判断有无工具调用 -> 执行工具 -> 结果回喂 -> 再循环）。不依赖 agent 抽象黑盒。

4. **RAG 后端复用 + Milvus**：复用本机 `F:\agent_develop\MODULAR-RAG-MCP-SERVER`（Hybrid 检索 BM25+Dense+RRF + 两段式 Rerank + MCP 暴露；复用 llm_factory/trace/evaluator）；**给其 VectorStore 抽象基类加 Milvus 后端**（和 Chroma 并存,配置切换）；本地用 milvus-lite（嵌入式零外部服务）；知识库:大模型八股+真实面试题、算法岗面经、JD 库(mcp-jobs 沉淀)、公司/薪资公开数据、简历范本。

5. **Function calling 工具层（基础）**：统一工具注册表（MCP 工具 mcp-jobs/Google MCP + 内部函数 memory_search/profile_update 等,都注册成带 schema 的 tool,agent 用同一接口）；基础并行/串行；高风险工具标 requires_confirmation 触发 interrupt。

6. **HITL 闸门（基础）**：投递/打招呼、接 offer 必须人工确认（LangGraph interrupt）。

7. **求职周期工作流闭环**：意向 -> 规划师建画像+目标公司池 -> 匹配官搜新 JD -> 命中 -> 简历顾问定制 -> 面试官模拟+记录 -> 谈判师准备策略 -> HITL 确认投递 -> 跟踪 -> 复盘写入记忆 -> 循环。

8. **评估（基础）**：答案级（简历匹配度/面试题质量,复用 Ragas）+ 业务级（投递->面试转化率、面试通过率、拿 offer dogfood）。

9. **可观测性（基础）**：复用 MODULAR-RAG 全链路 trace（JSON Lines）+ Streamlit 基础 Dashboard（系统总览/数据浏览/追踪查看）。不依赖 LangSmith。

10. **分层目录结构**：`careercrew-ai`(复用 llm_factory) / `careercrew-core`(LangGraph supervisor+手写 ReAct+记忆+工具) / `careercrew-cli`(产品+工作流+HITL) / `careercrew-ui`(CLI 渲染+Streamlit) 四层文件夹组织。

11. **MCP 工具**：现成 mcp-jobs + Google MCP；自建求职者端 MCP 放后期。MVP 投递/进度跟踪用 mock。

12. **测试**：pytest, TDD, 分层（单元/集成/E2E）。

### 【B. 高级方向 - 理解/能讲/后期实现（不是必做,挑 1-2 个亮点实现即可）】

- **Hermes 完整版记忆**：Skill Library（先加载精简描述命中才加载全文）/ User Model 丰富化 / 反思自进化循环（Skill 自我改进、面经掌握度图谱）/ 记忆双通道检索（系统每轮自动检索 + Agent 主动 memory_search）。
- **compaction 完整策略**：token 占比触发（优先用模型真实 usage 不用字符/4）；保留区（最近~20K tokens 原封）+ 压缩区（分块总结->合并->写 JSONL compaction 条目带 firstKeptEntryId）；**Pre-compaction Memory Flush**（压缩前先静默跑一轮把重要信息写进长期记忆再压缩,防丢关键信息）。
- **Loop Engineering 视角**：把求职闭环建模为七步 Goal->Task->Loop->Execute->Evidence->Asset->Govern；三角色对位（职业规划师=Planner / 执行 agent=Developer / 面试官+评估=Reviewer,建设性对抗）；原则"Design the loop, not the perfect prompt"；**human-in-loop,默认 HITL,仅低风险自动化**。
- **手写 ReAct 高级**：工具并行/串行策略（parallel_safe 配置）、运行中插话(steering)、收尾追问(follow-up)、随时中断(abort)。
- **轨迹级评估**：路由准确率/工具调用合理性(precision/recall)/记忆利用率(memory_hit_rate)/ReAct 效率/Grounding/HITL 触发正确性/压缩无损性；LLM-as-judge + 黄金轨迹回放（append-only 树的红利）。
- **Delegate 三级授权**：只读草稿（高风险:投递/接offer/谈薪话术,必确认）-> 代发待确认（中风险）-> 主动执行（低风险:搜职位/出题/草稿）。细化基础 HITL。
- **Hooks 统一接口**：before_tool_call(HITL闸门) / before_model(记忆注入、context改写) / before_compaction(flush) / after_compaction。把散落的拦截点统一成 hook。
- **事件驱动 + 单向依赖**：core 只跑逻辑发事件不碰渲染,UI 订阅事件,一套 core 配 CLI + Dashboard 双前端。
- **自建求职者端 MCP**：仿 boss-zhipin-mcp 的 Playwright+CDP（投递/进度跟踪/面经采集）。

## 文档结构要求

1. 项目概述：设计理念、项目定位
2. 核心特点
3. **技术选型与架构设计（按 MVP/高级分层写,每节标注属于哪层）**：多 Agent 编排 / Agent 内核(ReAct) / 记忆系统 / Function calling 与工具层 / 向量库可插拔(Milvus) / MCP 工具层 / RAG 复用 / HITL / 求职周期工作流 / 评估体系 / 可观测性与 Dashboard / 分层目录结构；高级方向单独成节列清单
4. 测试方案：TDD,分层,agent 行为评估
5. 系统架构与模块设计：架构图(ASCII)、目录结构树、模块职责表、数据流(Ingestion/Query/Agent编排/记忆读写/Compaction)、配置驱动示例
6. 项目排期：A->N 阶段,每阶段明确目的,子任务含修改文件列表/实现的类函数/验收标准/测试方法,约 1 小时一增量,进度跟踪表。**MVP 在 A-L,高级亮点挑 1-2 个放 M-N**（建议阶段:A 骨架配置 / B LangGraph supervisor+手写 ReAct 骨架 / C 3 层记忆+append-only 树 / D RAG 接入+扩 Milvus 后端 / E 职位匹配官 / F 简历顾问 / G CLI+M1 闭环 / H 面试官+情景记忆 / I 记忆按需检索+compaction 基础版 / J 谈判+规划 / K HITL 接工具层 / L 评估+Dashboard / M 高级亮点(选:Loop 视角/Pre-compaction flush/多 agent 会诊) / N 自建 MCP+dogfood+收尾）

## 其他要求

- 语言：中文
- 技术栈：Python + LangGraph（编排）+ 手写 ReAct（agent 内核）,不引入 AutoGen/CrewAI
- RAG 复用 MODULAR-RAG-MCP-SERVER 并扩 Milvus 后端；向量库 Milvus Lite 本地 + Docker 演示,Chroma 兜底,配置切换
- 会话存储:append-only JSONL + parentId 树；LangGraph checkpointer(SQLite) 短期层
- LLM 可插拔复用 llm_factory；测试 pytest；本地优先零外部服务（Milvus Lite 嵌入式）
- **MVP 优先,高级方向不阻塞主流程；spec 里高级内容明确标注"理解/能讲/后期实现"**

---

## 决策记录（供参考,不写进生成的 spec）

- **Agent 架构**：Hybrid（LangGraph supervisor 编排 + agent 节点内手写 ReAct）
- **Milvus 范围**：给 MODULAR-RAG 扩 Milvus 后端,CareerCrew 也用（Chroma 兜底）
- **记忆深度**：仿 Hermes,MVP 做 3 层基础版,完整版(Skill 库/User Model/反思/双通道)放高级方向
- **spec 范围**：MVP 核心(必须实现) + 高级方向(理解/能讲/后期实现) 两层
- **参考资料**：飞书文档《大模型应用/算法学习路线+八股+面试实战5》的 agent/记忆章节（Hermes/OpenClaw/Pi/Loop Engineering）；参考仓库 earendil-works/pi、openclaw/openclaw
