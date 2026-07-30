## 7. 可扩展性与未来展望

### 短期扩展（MVP 完成后）
- **更多 agent**：HR 跟进 agent、背调准备 agent。
- **更多知识库**：按公司/岗位细分 collection。
- **Dashboard 增强**：求职阶段看板、转化率趋势图。

### 高级方向落地（M-N 之后）
- **Hermes 完整记忆**：Skill Library + 反思自进化。
- **轨迹级评估**：LLM-as-judge + 黄金回放。
- **Delegate 三级授权**：细化闸门。
- **Hooks 统一接口**：before_tool_call / before_model / before_compaction / after_compaction。
- **事件驱动 + 单向依赖**：一套 core 配 CLI + Dashboard 双前端。

### 长期愿景
- **多用户**：checkpointer 换 Postgres、User Model 换 DB。
- **云端部署**：Milvus Docker/K8s、API 化。
- **求职知识库沉淀**：从代码 -> 八股 -> 面试技巧，形成完整求职知识库，反哺社区。

---

> **文档状态**：初稿 v0.2（自建 RAG + 硅基流动 + conda env）。后续按实际开发迭代细化各节（尤其是排期子任务的修改文件列表与验收标准，需在实现中校正）。
> **决策记录**：见 `prompts/gen_dev_spec.md` 末尾"决策记录"小节（供参考，不写进 spec）。
