"""PostgresMemoryDb 与真实 PostgreSQL 的行为回归测试。"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from careercrew_core.memory.db import PostgresMemoryDb


@pytest.fixture
def postgres_dsn() -> str:
    dsn = os.environ.get("POSTGRES_TEST_DSN")
    if not dsn:
        pytest.skip("需设置 POSTGRES_TEST_DSN 以运行真实 PostgreSQL 测试")
    return dsn


@pytest.mark.integration
def test_latest_episodic_orders_by_timestamp_then_id(postgres_dsn: str) -> None:
    """最新事件按 ts 降序，相同 ts 时按 id 降序，而非按插入顺序。"""
    db = PostgresMemoryDb(postgres_dsn)
    user_id = f"postgres-order-{uuid4().hex}"
    thread_id = "ordering"
    try:
        # 先写最新事件，再写较旧事件，确保结果不依赖插入顺序。
        db.insert_episodic(
            user_id, thread_id, "e_010", None, "event", {"order": 1},
            "2026-08-15T12:00:00+00:00",
        )
        db.insert_episodic(
            user_id, thread_id, "e_001", None, "event", {"order": 2},
            "2026-08-15T11:00:00+00:00",
        )
        # 同一最新时间戳中，后写的较小 id 不能取代较大 id。
        db.insert_episodic(
            user_id, thread_id, "e_009", None, "event", {"order": 3},
            "2026-08-15T12:00:00+00:00",
        )

        latest = db.latest_episodic(user_id, thread_id)

        assert latest is not None
        assert latest["id"] == "e_010"
    finally:
        db.delete_episodic(user_id, thread_id=thread_id)
