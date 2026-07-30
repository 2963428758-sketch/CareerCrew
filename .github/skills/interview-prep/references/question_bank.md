# CareerCrew 面试题库

> v0.1 starter - 基于 DEV_SPEC 设计级内容。代码落地后补充代码级细节与更多题目。
> 选题规则见 SKILL.md Phase 0.6：按 `[DICE]` 掷骰显式编号选题，禁止"注意力吸引"选题。

---

## 【开场题池】（方向 1 首题，共 12 道）

1. 先介绍一下 CareerCrew 这个项目，它解决什么问题？跟市面上单点求职工具（只做简历或只做面试）有什么本质区别？
2. 为什么用"多智能体团队"这个形态做求职顾问，而不是单个大模型一条龙搞定？
3. 项目里这 5 个 agent 是怎么分工的？supervisor 怎么决定该让哪个 agent 出场？
4. 你说求职是"高 stakes 决策"，这个判断怎么影响了你的架构设计？
5. CareerCrew 的"长期陪跑"靠什么实现？记忆系统在其中扮演什么角色？
6. 为什么 Demo 入口选 CLI 优先而不是直接做 Web？
7. 项目复用了 MODULAR-RAG-MCP-SERVER，复用了哪些能力？为什么不从头写？
8. 你给 MODULAR-RAG 扩了 Milvus 后端，这个扩展的必要性在哪？
9. 项目里"教是最好的学"是什么意思？Skill 体系怎么体现这点？
10. 求职周期闭环有哪几个阶段？哪些阶段必须人工确认？
11. 如果让你用一句话向面试官讲清这个项目的技术深度，你会怎么说？
12. 这个项目最大的技术风险或难点是什么？你怎么应对的？

### 【追问候选池】（方向 1 即兴追问灵感，不直接念）
- 候选人提到"多 agent" -> "这几个 agent 之间会协作还是会诊？会诊怎么实现？"
- 候选人提到"记忆" -> "记忆会一直增长吗？怎么压缩？"
- 候选人提到"HITL" -> "HITL 的中断-恢复怎么保证状态一致？"
- 候选人提到"复用 MODULAR-RAG" -> "复用的话，CareerCrew 自己的核心创新在哪？"

---

## 【方向 2：简历深挖题池】

### P1 - 量化指标题池
1. 你简历里写"5 个 agent"，这 5 个是怎么定出来的？为什么是 5 个不是 3 个或 10 个？
2. 简历提到"三层记忆"，这三层的边界你怎么划的？为什么不是两层或四层？
3. 你说检索准确率 90%+，这个数怎么测的？用的什么 golden set？
4. 简历写"61 个子任务自动推进"，auto-coder 怎么知道下一个任务是什么？出错怎么办？

### P2 - 强动词题池（"主导/设计/独立完成"）
1. 你说你"设计"了 Hybrid Agent 架构，LangGraph 和手写 ReAct 的分工边界你是怎么定的？
2. 你"主导"了记忆系统设计，append-only JSONL + parentId 树这个方案是你想出来的还是参考的？参考了什么？
3. 你"实现"了 HITL 闸门，interrupt 之后用户拒绝了，系统怎么回到上一个安全状态？

### P3 - 技术词汇题池
1. 简历提到 LangGraph supervisor，supervisor 节点和 agent 节点的职责怎么分？
2. 简历提到 ReAct，你手写的 ReAct 和 LangGraph 自带的 create_react_agent 有什么区别？为什么不用自带的？
3. 简历提到 Milvus，为什么选 Milvus 不选 Chroma？又为什么保留 Chroma 兜底？
4. 简历提到 compaction，compaction 触发的时机怎么判断？用 token 占比还是别的？

### 【无简历题库】
1. 这个项目里你最得意的设计决策是哪个？为什么？
2. 如果重新做一遍，你会改什么？
3. 项目里哪个模块最难？难在哪？

---

## 【方向 3：技术深挖题库】（A-F 六组）

### A 组 - 多 Agent 编排
1. LangGraph supervisor 的路由逻辑写在哪？输入是什么 state 字段？
2. supervisor 怎么判断该结束还是继续路由？结束条件是什么？
3. 多 agent 会诊（高级）怎么实现？fan-out 之后怎么 join？
4. checkpointer 用 SQLite，thread 级状态持久化了哪些字段？进程重启怎么恢复？
5. 求职阶段状态机有哪几个状态？状态转换由谁触发？

### B 组 - Agent 内核（手写 ReAct）
1. 手写 ReAct 的 while 循环，每一轮具体做哪几步？
2. 怎么判断 LLM 返回里有没有 tool_call？解析的是哪个字段？
3. 轮次上限怎么设？超限了怎么办？
4. 上下文每轮怎么组装？短期对话、记忆、工具结果怎么拼？
5. 为什么不用 LangGraph 的 create_react_agent 黑盒，非要手写？

### C 组 - 记忆系统
1. 情景记忆为什么用 append-only JSONL 不用数据库？parentId 树解决了什么问题？
2. 从叶子回溯到根重建上下文，具体算法是什么？时间复杂度？
3. 情景记忆的向量索引存哪个 Milvus collection？和知识库怎么隔离？
4. User Model 为什么用结构化 JSON 不用自由文本？字段约束怎么保证？
5. compaction 的保留区和压缩区怎么划？压缩后怎么保证关键信息不丢？
6. （高级）Pre-compaction Memory Flush 是什么？为什么压缩前要先 flush？

### D 组 - 工具层与 MCP
1. MCP 工具和内部函数怎么统一注册的？schema 长什么样？
2. agent 调工具时，MCP 工具和内部函数的调用路径一样吗？
3. requires_confirmation 怎么标记？触发后流程是什么？
4. rag_query 工具怎么封装 MODULAR-RAG 的检索？agent 怎么知道该用它？
5. MVP 阶段投递用 mock，mock 和真实 MCP 怎么无缝替换？

### E 组 - 向量库与 RAG
1. 给 MODULAR-RAG 加 Milvus 后端，实现了 BaseVectorStore 的哪些方法？
2. Milvus 的 Dense + Sparse 混合检索和 MODULAR-RAG 的双路编码怎么配合？
3. milvus-lite 嵌入式和 Docker 版 Milvus 怎么配置切换？
4. 知识库 collection 和情景记忆 collection 为什么隔离不共用？
5. Chroma 兜底在什么场景下启用？切换时数据怎么办？

### F 组 - HITL / 工作流 / 评估
1. LangGraph interrupt 的机制是什么？暂停后状态存哪？恢复怎么触发？
2. 投递/打招呼/接 offer/谈薪话术这四类必确认动作，怎么在工具层标记的？
3. 求职周期闭环的 9 个阶段，阶段切换由用户驱动还是 agent 产出触发？
4. 答案级评估和业务级评估分别评估什么？业务级的"转化率"数据从哪来？
5. （高级）轨迹级评估怎么做？黄金轨迹回放利用了 append-only 树的什么特性？
6. （高级）Delegate 三级授权是哪三级？和基础 HITL 是什么关系？
