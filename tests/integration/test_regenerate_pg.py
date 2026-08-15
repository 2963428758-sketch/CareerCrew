"""T1.6 PG 集成测试：regeneration_keys 幂等表迁移 + user 消息 metadata 真库往返。

缺 POSTGRES_TEST_DSN 跳过；复用一次性库 guard。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from careercrew_core.conversation.db import PostgresConversationDb
from careercrew_core.conversation.store import ConversationStore, OwnershipError

DSN = os.environ.get("POSTGRES_TEST_DSN", "").strip()

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set"),
]


def _require_disposable_db(dsn: str) -> None:
    dbname = urlparse(dsn.replace("postgresql://", "postgres://")).path.lstrip("/")
    if dbname == "careercrew":
        raise RuntimeError(
            "POSTGRES_TEST_DSN 指向生产库 careercrew，拒绝运行。请使用一次性测试库。"
        )


@pytest.fixture
def store_and_db():
    import psycopg

    _require_disposable_db(DSN)
    db = PostgresConversationDb(DSN)
    yield ConversationStore(db), db
    with psycopg.connect(DSN) as conn, conn.transaction():
        conn.execute("DELETE FROM regeneration_keys")
        conn.execute("DELETE FROM agent_run_tool_calls")
        conn.execute("DELETE FROM agent_run_retrievals")
        conn.execute("DELETE FROM agent_runs")
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM conversation_turns")
        conn.execute("DELETE FROM conversations")


def test_regeneration_keys_table_exists(store_and_db):
    _, db = store_and_db
    db._ensure()
    import psycopg

    with psycopg.connect(DSN) as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
            ("regeneration_keys",),
        ).fetchone()
        assert row is not None, "regeneration_keys table missing"


def test_regeneration_keys_idempotent_migration(store_and_db):
    """regeneration_keys 幂等迁移 + UNIQUE(user_id, key) 生效 + 二次 create 返回 None。"""
    store, db = store_and_db
    db._ensure()
    db._ensure()  # 迁移幂等

    mid = str(uuid4())
    assert store.create_regeneration("u_1", "k1", mid) == mid
    assert store.get_regeneration("u_1", "k1") == mid
    # 同 key 二次 → 冲突返回 None
    assert store.create_regeneration("u_1", "k1", str(uuid4())) is None
    # 不同 user 同 key 独立
    assert store.create_regeneration("u_2", "k1", str(uuid4())) is not None


def test_user_message_metadata_roundtrip_pg(store_and_db):
    """add_user_message(metadata=...) 在真库持久化 JSONB，None 保持 NULL。"""
    store, db = store_and_db
    uid = "u_meta_user"
    conv = store.ensure_conversation(str(uuid4()), uid, "knowledge", "T")
    turn = store.next_turn(conv["id"], uid)
    msg = store.add_user_message(
        turn["id"], conv["id"], uid, "q", "completed",
        metadata={"category": "resume", "scope": "public"},
    )
    assert msg["metadata"] == {"category": "resume", "scope": "public"}
    persisted = db.get_message(uid, msg["id"])
    assert persisted["metadata"] == {"category": "resume", "scope": "public"}

    msg2 = store.add_user_message(turn["id"], conv["id"], uid, "q2", "completed")
    assert msg2["metadata"] is None
    assert db.get_message(uid, msg2["id"])["metadata"] is None
