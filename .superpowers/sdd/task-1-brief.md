### Task 1: 修复 Postgres 情景记忆最新事件排序

修改 `careercrew_core/memory/db.py` 中 Postgres `latest_episodic` 查询为 `ORDER BY ts DESC, id DESC`。添加真实 Postgres 回归测试，覆盖不按插入顺序的时间戳及相同时间戳的 id 决胜；将该测试接入带 Postgres service 的 CI job。不得只修改内存 fake 或只增加字符串断言测试。
