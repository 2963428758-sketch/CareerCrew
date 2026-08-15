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
    uid = "u_001"  # user_id 为 VARCHAR(64)：真实账户 id 形状（非 UUID）
    thread_id = str(uuid4())
    store.ensure_conversation(thread_id, uid, "chat", "T")
    turn1 = store.next_turn(thread_id, uid)
    turn2 = store.next_turn(thread_id, uid)
    assert turn1["sequence_no"] == 1
    assert turn2["sequence_no"] == 2
    assert turn1["id"] != turn2["id"]


def _begin_chat_turn(store, uid, module="chat", title="T", model="m"):
    """按 T1.2 生命周期辅助的顺序搭一整套 turn（含 streaming 接线）。"""
    legacy = f"t-{uuid4().hex}"
    conv = store.ensure_conversation(legacy, uid, module, title)
    turn = store.next_turn(legacy, uid)
    user_msg = store.add_user_message(turn["id"], conv["id"], uid, "hello", "completed")
    # 流式：assistant 消息先为空内容，set_message_status(streaming) 后开始跑
    asst = store.add_assistant_message(turn["id"], conv["id"], uid, "", None, None)
    asst = store.set_message_status(uid, asst["id"], "streaming")
    run = store.start_run(
        thread_id=conv["id"], turn_id=turn["id"], message_id=asst["id"],
        user_id=uid, module=module, agent_id="a", model=model,
        prompt_version="unversioned", agent_version="1",
        status="streaming",
    )
    # run 生成后回填 message.run_id（begin_turn 顺序）
    asst = store.set_message_run_id(uid, asst["id"], run["id"])
    return conv, turn, user_msg, asst, run


def test_full_flow(store_and_db):
    store, _ = store_and_db
    uid = "u_001"
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
    # set_message_status 所有权检查（VARCHAR user_id）
    updated = store.set_message_status(uid, asst["id"], "completed")
    assert updated["status"] == "completed"
    with pytest.raises(OwnershipError):
        store.set_message_status("u_002", asst["id"], "completed")
    # 所有权：跨用户拒绝
    with pytest.raises(OwnershipError):
        store.list_messages(conv["id"], "u_002")


def test_set_message_content_roundtrip(store_and_db):
    """set_message_content：流式结束后内容回写 + 状态 + completed_at 落库。"""
    store, db = store_and_db
    uid = "u_content"
    _, _, _, asst, _ = _begin_chat_turn(store, uid)
    # 断言 streaming 起始态：空内容、无 completed_at
    raw = db.get_message(uid, asst["id"])
    assert raw["content"] == ""
    assert raw["status"] == "streaming"
    assert raw["completed_at"] is None
    # 流式结束写最终内容
    updated = store.set_message_content(uid, asst["id"], "final answer")
    assert updated["content"] == "final answer"
    assert updated["status"] == "completed"
    assert updated["completed_at"] is not None
    # 真库回读（绕过 store）确认持久化
    persisted = db.get_message(uid, asst["id"])
    assert persisted["content"] == "final answer"
    assert persisted["status"] == "completed"
    # 显式 status 参数生效
    store.set_message_content(uid, asst["id"], "retry", status="failed")
    assert db.get_message(uid, asst["id"])["status"] == "failed"
    assert db.get_message(uid, asst["id"])["content"] == "retry"
    # 所有权
    with pytest.raises(OwnershipError):
        store.set_message_content("u_other", asst["id"], "x")


def test_set_message_content_metadata_roundtrip(store_and_db):
    """metadata JSONB 列：set_message_content 写入富结构并在真库持久化。"""
    store, db = store_and_db
    uid = "u_meta"
    _, _, _, asst, _ = _begin_chat_turn(store, uid)
    updated = store.set_message_content(uid, asst["id"], "done", metadata={"sources": [{"doc": "note"}]})
    assert updated["metadata"] == {"sources": [{"doc": "note"}]}
    persisted = db.get_message(uid, asst["id"])
    assert persisted["metadata"] == {"sources": [{"doc": "note"}]}
    # 再次写入不传 metadata → 保持不变
    again = store.set_message_content(uid, asst["id"], "done2")
    assert again["metadata"] == {"sources": [{"doc": "note"}]}
    assert db.get_message(uid, asst["id"])["metadata"] == {"sources": [{"doc": "note"}]}


def test_set_message_run_id_roundtrip(store_and_db):
    """set_message_run_id：run_id 回填 message 并持久化。"""
    store, db = store_and_db
    uid = "u_runid"
    legacy = f"t-{uuid4().hex}"
    conv = store.ensure_conversation(legacy, uid, "chat")
    turn = store.next_turn(legacy, uid)
    store.add_user_message(turn["id"], conv["id"], uid, "q", "completed")
    asst = store.add_assistant_message(turn["id"], conv["id"], uid, "", None, None)
    assert asst["run_id"] is None
    run = store.start_run(
        thread_id=conv["id"], turn_id=turn["id"], message_id=asst["id"],
        user_id=uid, module="chat", agent_id="a", model="m",
    )
    # 回填前 message.run_id 仍为 NULL（真库）
    assert db.get_message(uid, asst["id"])["run_id"] is None
    updated = store.set_message_run_id(uid, asst["id"], run["id"])
    assert updated["run_id"] == run["id"]
    assert db.get_message(uid, asst["id"])["run_id"] == run["id"]
    with pytest.raises(OwnershipError):
        store.set_message_run_id("u_other", asst["id"], run["id"])


def test_run_lifecycle(store_and_db):
    """start_run → finish_run：status/latency/finished_at/tokens/error 持久化。"""
    store, db = store_and_db
    uid = "u_run"
    _, _, _, asst, run = _begin_chat_turn(store, uid)
    # T1.2 接线：begin_turn 直接以 streaming 插入（非终态，finished_at 为 NULL）
    assert db.get_run(uid, run["id"])["status"] == "streaming"
    assert db.get_run(uid, run["id"])["finished_at"] is None
    # finish_run 写 status + tokens + latency + finished_at
    finished = store.finish_run(
        user_id=uid, run_id=run["id"], status="completed",
        input_tokens=10, output_tokens=20, total_tokens=30, latency_ms=420,
        langsmith_run_id="ls-123",
    )
    assert finished["status"] == "completed"
    assert finished["input_tokens"] == 10
    assert finished["output_tokens"] == 20
    assert finished["total_tokens"] == 30
    assert finished["latency_ms"] == 420
    assert finished["langsmith_run_id"] == "ls-123"
    assert finished["finished_at"] is not None
    persisted = db.get_run(uid, run["id"])
    assert persisted["status"] == "completed"
    assert persisted["latency_ms"] == 420
    assert persisted["finished_at"] is not None


def test_start_run_streaming_status(store_and_db):
    """start_run(status="streaming") 在真实 Postgres 上直接落 streaming 初始态。"""
    store, db = store_and_db
    uid = "u_run_stream"
    _, _, _, asst, run = _begin_chat_turn(store, uid)
    # 直接以 streaming 插入，非终态 → finished_at 为 NULL
    persisted = db.get_run(uid, run["id"])
    assert persisted["status"] == "streaming"
    assert persisted["finished_at"] is None
    # 终态迁移（finish_run 保留给终态）从 streaming 正常收尾
    finished = store.finish_run(user_id=uid, run_id=run["id"], status="completed")
    assert finished["status"] == "completed"
    assert db.get_run(uid, run["id"])["finished_at"] is not None


def test_run_failure_persisted(store_and_db):
    """finish_run 失败路径：status + error_* 字段落库。"""
    store, db = store_and_db
    uid = "u_fail"
    _, _, _, _, run = _begin_chat_turn(store, uid)
    store.finish_run(
        user_id=uid, run_id=run["id"], status="failed",
        error_type="AgentError", error_code="E1", error_summary="boom",
    )
    persisted = db.get_run(uid, run["id"])
    assert persisted["status"] == "failed"
    assert persisted["error_type"] == "AgentError"
    assert persisted["error_code"] == "E1"
    assert persisted["error_summary"] == "boom"
    assert persisted["finished_at"] is not None
    with pytest.raises(OwnershipError):
        store.finish_run(user_id="u_other", run_id=run["id"], status="completed")
