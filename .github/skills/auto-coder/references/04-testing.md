## 4. 测试方案

### 4.1 设计理念：测试驱动开发 (TDD)

本项目采用 **TDD** 作为核心开发范式，每个组件实现前先明确预期行为。

**核心原则**：
- **早测试、常测试**：每个模块实现同时编写单元测试。
- **测试即文档**：测试用例是行为规范，新开发者读测试即可理解模块功能。
- **快速反馈循环**：单元测试秒级完成，支持高频执行。
- **分层测试金字塔**：大量单元测试为基座，中量集成测试保障协作，少量 E2E 验证完整流程。

```
        /\
       /E2E\         <- 少量：求职闭环关键流程
      /------\
     /Integration\   <- 中量：supervisor+agent+工具+记忆协作
    /------------\
   /  Unit Tests  \  <- 大量：单个函数/类（ReAct 循环、记忆读写、工具路由）
  /________________\
```

### 4.2 测试分层策略

#### 4.2.1 单元测试 (Unit Tests)
隔离外部依赖（LLM / Milvus / MCP），验证内部逻辑。

| 模块 | 测试重点 | 典型用例 |
|------|---------|---------|
| **ReAct 内核** | 循环逻辑、轮次上限、工具调用判定 | Mock LLM 返回 tool_call -> 验证执行+回喂；无 tool_call -> 验证 break；超轮次 -> 抛错 |
| **记忆 - 情景** | append-only、parentId 树、回溯重建 | 写入后 parentId 链正确；从叶子回溯到根拼接上下文完整 |
| **记忆 - User Model** | 结构化读写、字段约束 | `profile_update` 更新字段；非法字段拒绝 |
| **记忆 - compaction** | 触发阈值、保留区、压缩条目 | token 占比超阈值触发；保留区原封；compaction 条目带 `firstKeptEntryId` |
| **工具注册表** | 注册、路由、requires_confirmation | MCP/内部工具统一 schema；高风险工具触发 Interrupt 信号 |
| **supervisor 路由** | 阶段->agent 路由 | 意图+阶段 -> 正确 agent；多 agent 会诊 fan-out |
| **Milvus 后端** | upsert/query 契约 | roundtrip 确定性；Dense+Sparse 混合检索；collection 隔离 |

**技术选型**：`pytest` + `unittest.mock`/`pytest-mock` + `pytest-check`。

#### 4.2.2 集成测试 (Integration Tests)
验证多组件协作。

| 场景 | 验证要点 |
|------|---------|
| **supervisor + agent + ReAct** | 路由到 agent -> ReAct 执行工具 -> 返回 supervisor |
| **agent + 记忆** | ReAct 主动 `memory_search` -> 结果回喂 -> 写情景记忆 |
| **agent + RAG** | `rag_query` 调自建 RAG 检索 -> 结果回喂 |
| **HITL 流程** | 高风险工具 -> interrupt -> 人工确认 -> 恢复 -> 写记忆 |
| **Milvus + RAG** | 知识库 ingestion -> 检索 roundtrip（真实 milvus-lite） |

#### 4.2.3 端到端测试 (E2E Tests)
模拟真实求职闭环：
- **场景 1：意向->匹配->简历** 部分闭环（M1 验收）。
- **场景 2：面试模拟** 出题->问答->评分->写面经。
- **场景 3：HITL 投递** 谈薪->确认投递->跟踪->复盘。
- **场景 4：dogfood** 用自身知识库跑完整求职周期。

### 4.3 Agent 行为评估测试

针对 agent 系统特有的评估（区别于普通函数测试）：

1. **路由准确率**：给定意图+阶段，supervisor 是否路由到正确 agent（golden 路由集）。
2. **工具调用合理性**：precision/recall（该调的调了没、不该调的乱调没）。
3. **记忆利用率**：`memory_hit_rate`（已有相关记忆时是否被检索利用）。
4. **HITL 触发正确性**：高风险动作是否必然触发确认、低风险是否不误触发。
5. **ReAct 效率**：达到目标所需轮次（避免无谓多轮）。
6. **Grounding**：答案是否有知识库/记忆依据（不幻觉）。

> 轨迹级量化评估（LLM-as-judge + 黄金回放）属高级方向，MVP 阶段用 golden 集断言 + 人工抽检。

### 4.4 测试工具链

- **框架**：`pytest`（参数化、Fixture）。
- **Mock**：`unittest.mock`（LLM / MCP / Milvus）。
- **Agent 评估**：golden 路由集 + golden 轨迹集（`tests/fixtures/`）。
- **覆盖率目标**：单元测试核心逻辑 ≥ 80%；关键路径集成测试 100%；E2E 至少 4 个关键流程。

---
