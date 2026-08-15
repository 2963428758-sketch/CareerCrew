"""ConversationStore 领域服务单元测试（FakeConversationDb）。

覆盖 ensure 幂等、legacy 映射、turn sequence、UNIQUE 冲突重试、消息排序与版本链、
所有权拒绝（OwnershipError）、run 生命周期、retrieval/tool_call 写入。
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from careercrew_core.conversation.db import FakeConversationDb
from careercrew_core.conversation.store import ConversationStore, OwnershipError


@pytest.fixture
def store() -> ConversationStore:
    return ConversationStore(FakeConversationDb())


def _uuid() -> str:
    return str(uuid4())


# ── ensure_conversation ──


def test_ensure_conversation_uuid_is_new(store):
    thread_id = _uuid()
    row = store.ensure_conversation(thread_id, "u_1", "chat", "Title")
    assert row["id"] == thread_id
    assert row["user_id"] == "u_1"
    assert row["module"] == "chat"
    assert row["title"] == "Title"
    # UUID 输入不落地 legacy 映射
    assert row["legacy_thread_id"] is None


def test_ensure_conversation_uuid_idempotent(store):
    thread_id = _uuid()
    r1 = store.ensure_conversation(thread_id, "u_1", "chat", "A")
    r2 = store.ensure_conversation(thread_id, "u_1", "chat", "B")
    assert r1["id"] == r2["id"] == thread_id


def test_ensure_conversation_legacy_maps_same_uuid(store):
    legacy = f"t-{42}"
    r1 = store.ensure_conversation(legacy, "u_1", "chat", "T")
    r2 = store.ensure_conversation(legacy, "u_1", "chat", "T")
    assert r1["id"] == r2["id"]  # 同 legacy id 复用同一 UUID
    assert r2["legacy_thread_id"] == legacy


def test_ensure_conversation_different_legacy_different_uuid(store):
    r1 = store.ensure_conversation("t-1", "u_1", "chat", "T")
    r2 = store.ensure_conversation("t-2", "u_1", "chat", "T")
    assert r1["id"] != r2["id"]


# ── get_conversation ──


def test_get_conversation_by_uuid_and_legacy(store):
    store.ensure_conversation("t-99", "u_1", "chat", "T")
    row = store.get_conversation("t-99", "u_1")
    assert row is not None
    by_legacy = store.get_conversation("t-99", "u_1")
    by_id = store.get_conversation(row["id"], "u_1")
    assert by_legacy["id"] == by_id["id"] == row["id"]


def test_get_conversation_rejects_wrong_owner(store):
    store.ensure_conversation("t-99", "u_1", "chat", "T")
    with pytest.raises(OwnershipError):
        store.get_conversation("t-99", "u_2")


def test_get_conversation_missing_returns_none(store):
    assert store.get_conversation(_uuid(), "u_1") is None


# ── next_turn ──


def test_next_turn_sequence_increments(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    t1 = store.next_turn("t-1", "u_1")
    t2 = store.next_turn("t-1", "u_1")
    assert t1["sequence_no"] == 1
    assert t2["sequence_no"] == 2


def test_next_turn_rejects_wrong_owner(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    with pytest.raises(OwnershipError):
        store.next_turn("t-1", "u_2")


class _RacyDb(FakeConversationDb):
    """模拟并发 MAX+1 撞车：第一次 insert_turn 抛 UNIQUE 冲突，重试后成功。"""

    def __init__(self):
        super().__init__()
        self._inserted = 0

    def insert_turn(self, turn_id, thread_id, user_id, sequence_no):
        self._inserted += 1
        if self._inserted == 1:
            raise _UniqueViolation()
        return super().insert_turn(turn_id, thread_id, user_id, sequence_no)


class _UniqueViolation(Exception):
    pass


def test_next_turn_retries_on_unique_conflict():
    db = _RacyDb()
    store = ConversationStore(db)
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    assert turn["sequence_no"] == 1
    assert db._inserted == 2  # 第一次撞车，重试成功


# ── messages ──


def test_add_user_and_assistant_messages(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    user_msg = store.add_user_message(turn["id"], turn["thread_id"], "u_1", "hello", "completed")
    run_id = _uuid()
    asst_msg = store.add_assistant_message(
        turn["id"], turn["thread_id"], "u_1", "hi there", run_id, None
    )
    assert user_msg["role"] == "user"
    assert asst_msg["role"] == "assistant"
    assert asst_msg["run_id"] == run_id


def test_list_messages_orders_by_turn_then_created(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    t1 = store.next_turn("t-1", "u_1")
    store.add_user_message(t1["id"], t1["thread_id"], "u_1", "q1", "completed")
    store.add_assistant_message(t1["id"], t1["thread_id"], "u_1", "a1", _uuid(), None)
    t2 = store.next_turn("t-1", "u_1")
    store.add_user_message(t2["id"], t2["thread_id"], "u_1", "q2", "completed")
    store.add_assistant_message(t2["id"], t2["thread_id"], "u_1", "a2", _uuid(), None)

    msgs = store.list_messages("t-1", "u_1")
    contents = [m["content"] for m in msgs]
    assert contents == ["q1", "a1", "q2", "a2"]


def test_list_messages_includes_regenerated_from(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    first = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "v1", _uuid(), None)
    regenerated = store.add_assistant_message(
        turn["id"], turn["thread_id"], "u_1", "v2", _uuid(), first["id"]
    )
    assert regenerated["regenerated_from_message_id"] == first["id"]


def test_list_message_versions_returns_chain(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    store.add_user_message(turn["id"], turn["thread_id"], "u_1", "q", "completed")
    v1 = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "v1", _uuid(), None)
    v2 = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "v2", _uuid(), v1["id"])
    v3 = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "v3", _uuid(), v2["id"])

    versions = store.list_message_versions(v3["id"], "u_1")
    assert [v["id"] for v in versions] == [v1["id"], v2["id"], v3["id"]]


def test_set_message_status_sets_completed_at(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "stream", _uuid(), None)
    assert msg["completed_at"] is None
    updated = store.set_message_status("u_1", msg["id"], "completed")
    assert updated["status"] == "completed"
    assert updated["completed_at"] is not None


def test_set_message_status_rejects_wrong_owner(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "stream", _uuid(), None)
    with pytest.raises(OwnershipError):
        store.set_message_status("u_2", msg["id"], "completed")


def test_list_messages_rejects_wrong_owner(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    store.add_user_message(turn["id"], turn["thread_id"], "u_1", "q", "completed")
    with pytest.raises(OwnershipError):
        store.list_messages("t-1", "u_2")


def test_list_message_versions_rejects_wrong_owner(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    store.add_user_message(turn["id"], turn["thread_id"], "u_1", "q", "completed")
    v1 = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "v1", _uuid(), None)
    with pytest.raises(OwnershipError):
        store.list_message_versions(v1["id"], "u_2")


# ── runs / retrieval / tool_call ──


def test_run_lifecycle(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)
    run = store.start_run(
        thread_id=turn["thread_id"],
        turn_id=turn["id"],
        message_id=msg["id"],
        user_id="u_1",
        module="chat",
        agent_id="resume_advisor",
        model="deepseek-v4",
        prompt_version="unversioned",
        agent_version="1.0",
    )
    assert run["status"] == "pending"
    assert run["started_at"] is not None

    finished = store.finish_run(
        user_id="u_1",
        run_id=run["id"],
        status="completed",
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        latency_ms=123,
        langsmith_run_id="ls-1",
    )
    assert finished["status"] == "completed"
    assert finished["input_tokens"] == 10
    assert finished["finished_at"] is not None


def test_run_requires_user_ownership(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)
    run = store.start_run(
        thread_id=turn["thread_id"], turn_id=turn["id"], message_id=msg["id"],
        user_id="u_1", module="chat", agent_id="a", model="m",
        prompt_version="unversioned", agent_version="1",
    )
    with pytest.raises(OwnershipError):
        store.finish_run(user_id="u_2", run_id=run["id"], status="completed")


def test_retrieval_and_tool_call_writes(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)
    run = store.start_run(
        thread_id=turn["thread_id"], turn_id=turn["id"], message_id=msg["id"],
        user_id="u_1", module="chat", agent_id="a", model="m",
        prompt_version="unversioned", agent_version="1",
    )
    retrieval = store.add_retrieval(
        user_id="u_1", run_id=run["id"], query_index=0,
        query_text_redacted="q", scope="kb", document_id="d1", chunk_id="c1",
        recall_score=0.9, rerank_score=0.8, rank_before=1, rank_after=1,
        used_in_final_context=True,
    )
    assert retrieval["document_id"] == "d1"
    assert retrieval["used_in_final_context"] is True

    tool_call = store.add_tool_call(
        user_id="u_1", run_id=run["id"], tool_name="search", input_redacted={"a": 1},
        output_summary="ok", status="completed", duration_ms=5,
        requires_hitl=False,
    )
    assert tool_call["tool_name"] == "search"
    assert tool_call["status"] == "completed"


def test_retrieval_and_tool_call_reject_wrong_owner(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)
    run = store.start_run(
        thread_id=turn["thread_id"], turn_id=turn["id"], message_id=msg["id"],
        user_id="u_1", module="chat", agent_id="a", model="m",
        prompt_version="unversioned", agent_version="1",
    )
    with pytest.raises(OwnershipError):
        store.add_retrieval(user_id="u_2", run_id=run["id"], query_index=0)
    with pytest.raises(OwnershipError):
        store.add_tool_call(user_id="u_2", run_id=run["id"], tool_name="x", status="ok")
