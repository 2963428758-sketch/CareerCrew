"""并行会话写入安全：多个会话同时写情景记忆，id 必须唯一、内容不得互相覆盖。"""
from __future__ import annotations

import threading

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry


def test_concurrent_writes_get_distinct_ids() -> None:
    """8 个线程各自写 10 条：id 分配（MAX+1）与插入必须在同一把锁内，否则并发取到同一 id 互相覆盖。"""
    db = FakeMemoryDb()

    def writer(n: int) -> None:
        ep = EpisodicMemory(db, user_id="u1", thread_id=f"t{n}")
        for i in range(10):
            ep.write(MemoryEntry(type="user_message", content=f"{n}-{i}"))

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = db.list_episodic("u1")
    ids = [r["id"] for r in rows]
    assert len(rows) == 80
    assert len(ids) == len(set(ids))  # 无 id 复用/覆盖
    contents = {r["content"] for r in rows}
    assert len(contents) == 80  # 无内容被覆盖
