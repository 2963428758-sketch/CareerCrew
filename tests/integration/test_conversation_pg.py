"""PostgresConversationDb 真实建表 + ConversationStore 行为回归测试。

缺 POSTGRES_TEST_DSN 跳过；用一次性库（guard 拒绝生产库 careercrew）。
验证：真实表创建、UNIQUE(thread_id, sequence_no) 实际生效、迁移幂等。
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
    """安全闸：只允许指向一次性测试库（不清也不污染生产）。"""
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
    # 清理本测试创建的数据（用随机 user_id 避免跨测试串扰）
    with psycopg.connect(DSN) as conn, conn.transaction():
        conn.execute("DELETE FROM agent_run_tool_calls")
        conn.execute("DELETE FROM agent_run_retrievals")
        conn.execute("DELETE FROM agent_runs")
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM conversation_turns")
        conn.execute("DELETE FROM conversations")


def test_tables_exist(store_and_db):
    _, db = store_and_db
    db._ensure()
    import psycopg

    with psycopg.connect(DSN) as conn:
        for table in (
            "conversations",
            "conversation_turns",
            "messages",
            "agent_runs",
            "agent_run_retrievals",
            "agent_run_tool_calls",
        ):
            row = conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,)
            ).fetchone()
            assert row is not None, f"table {table} missing"


def test_migration_idempotent(store_and_db):
    # 二次初始化（重复建表 + ALTER ADD COLUMN IF NOT EXISTS）不应报错
    _, db = store_and_db
    db._ensure()
    db._ensure()


def test_unique_sequence_enforced(store_and_db):
    """UNIQUE(thread_id, sequence_no) 在真实库上实际生效。"""
    store, _ = store_and_db
    uid = str(uuid4())  # user_id 按 DDL 为 UUID
    thread_id = str(uuid4())
    store.ensure_conversation(thread_id, uid, "chat", "T")
    turn1 = store.next_turn(thread_id, uid)
    turn2 = store.next_turn(thread_id, uid)
    assert turn1["sequence_no"] == 1
    assert turn2["sequence_no"] == 2
    assert turn1["id"] != turn2["id"]


def test_full_flow(store_and_db):
    store, _ = store_and_db
    uid = str(uuid4())
    legacy = f"t-{uuid4().hex}"
    conv = store.ensure_conversation(legacy, uid, "chat", "T")
    assert conv["legacy_thread_id"] == legacy
    turn = store.next_turn(legacy, uid)
    store.add_user_message(turn["id"], conv["id"], uid, "hello", "completed")
    asst = store.add_assistant_message(turn["id"], conv["id"], uid, "hi", None, None)
    run = store.start_run(
        thread_id=conv["id"], turn_id=turn["id"], message_id=asst["id"],
        user_id=uid, module="chat", agent_id="a", model="m",
        prompt_version="unversioned", agent_version="1",
    )
    store.finish_run(user_id=uid, run_id=run["id"], status="completed")
    # retrieval / tool_call（§8.2/§8.3，含 JSONB input_redacted）
    store.add_retrieval(user_id=uid, run_id=run["id"], query_index=0,
                        query_text_redacted="q", document_id="d1", chunk_id="c1")
    store.add_tool_call(user_id=uid, run_id=run["id"], tool_name="search",
                        input_redacted={"a": 1}, status="completed")
    msgs = store.list_messages(conv["id"], uid)
    assert [m["content"] for m in msgs] == ["hello", "hi"]
    # 所有权：跨用户拒绝
    with pytest.raises(OwnershipError):
        store.list_messages(conv["id"], str(uuid4()))
