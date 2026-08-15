# 评估数据（data/eval）

- `cases.jsonl`：评估用例（kind: route/retrieval/citation/tool/memory/consult），每行一个 JSON 对象。
- `fixtures/*.json`：离线观测值（`source: "fixture"`），供 PR 离线门禁使用。
- `baseline.json`：版本化基线（由 `python scripts/eval_runner.py --offline --update-baseline` 生成）。

## 运行方式

```bash
# 离线非回归门禁（PR 必跑；任一指标低于基线 0.01 即失败）
python scripts/eval_runner.py --offline --compare data/eval/baseline.json --fail-on-regression

# 更新基线（新功能带来合法指标变化时人工执行并提交）
python scripts/eval_runner.py --offline --update-baseline

# 真实模型评估（依赖本地 conda env：BGE-M3/Qdrant/硅基流动 API；nightly/manual）
python scripts/eval_runner.py --real
```

## 门禁原理

真实模型评估放在 nightly/manual；PR 只用 fixtures 验证 runner 与 schema 的非回归，
避免把不确定的真实模型分数作为发布门禁。
