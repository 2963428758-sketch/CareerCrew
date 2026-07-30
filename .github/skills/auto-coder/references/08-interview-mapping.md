## 8. 面试考点与简历亮点映射

> "教是最好的学"--每个模块对应的高频面试题与简历 bullet，开发时同步整理。配套 skill：`interview-prep`（模拟面试）/ `resume-writer`（写简历）/ `project-review`（复习）/ `project-learner`（知识点学习）。

| 模块 | 高频面试题 | 简历亮点 bullet |
|------|-----------|----------------|
| 多 Agent 编排 | LangGraph supervisor 怎么路由？为什么不纯 LangGraph？checkpointer 存什么？多 agent 会诊怎么做？ | 设计 5 agent + supervisor 状态机路由，9 阶段求职闭环可 dogfood |
| 手写 ReAct | 为什么不用 create_react_agent？怎么判 tool_call？轮次上限？每轮上下文怎么组装？ | 手写可见 ReAct 循环，工具推理过程全链路 trace 可回放，不依赖黑盒 |
| 三层记忆 | append-only 树解决什么？回溯算法复杂度？compaction 怎么触发/防丢？ | 仿 Hermes 三层记忆，append-only 树支持黄金轨迹回放与轨迹级评估 |
| BGE-M3 RAG | 三路输出怎么拿？为什么本地跑？sparse vs BM25 区别？colbert 代价？ | 自建 RAG：BGE-M3 三合一 + Contextual Chunking，检索失败率降 49% |
| Hybrid+RRF | RRF 公式？为什么用排名倒数不用分数？top_k 怎么定？ | Hybrid 检索 + RRF 融合 + bge-reranker 精排，两段式架构平衡查准与查全 |
| 文档加载 | 为什么用 MarkItDown？多格式怎么统一？BaseLoader 怎么抽象？ | 多格式文档加载（PDF/Word/Markdown）统一转 Markdown，MarkItDown + BaseLoader 可插拔 |
| Milvus 可插拔 | BaseVectorStore 怎么抽象？milvus-lite vs Docker？collection 隔离？ | 自建 Milvus 后端 + Chroma 兜底，配置驱动零代码切换向量库 |
| HITL 闸门 | interrupt 怎么恢复状态一致？哪些动作必确认？Delegate 三级？ | 高 stakes 决策默认 HITL，LangGraph interrupt 实现投递/接 offer 闸门 |
| 工具层 | MCP 与内部函数怎么统一？requires_confirmation 怎么标记？ | 统一工具注册表，MCP+内部函数同 schema，风险分级触发 HITL |
| 评估 | 答案级 vs 业务级 vs 轨迹级？业务数据从哪来？黄金回放？ | 答案级(Ragas)+业务级(转化率)+轨迹级(黄金回放) 三层评估闭环 |
| 可观测 | 为什么不用 LangSmith？trace schema？怎么定位坏 case？ | 自建全链路 trace(JSON Lines)+Streamlit Dashboard，零外部依赖可观测 |
| 工程化 | 四层依赖方向？TDD 分层？conda env？CI？ | 四层单向依赖架构 + TDD 分层测试，单元覆盖≥80% |

> 每完成一个模块：用 `project-review` / `project-learner` 自测掌握度，用 `resume-writer` 沉淀简历 bullet，用 `interview-prep` 模拟面试。

---
