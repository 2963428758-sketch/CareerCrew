"""ConversationStore 领域服务单元测试（FakeConversationDb）。

覆盖 ensure 幂等、legacy 映射、turn sequence、UNIQUE 冲突重试、消息排序与版本链、
所有权拒绝（OwnershipError）、run 生命周期、retrieval/tool_call 写入。
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from careercrew_core.conversation.db import FakeConversationDb, SequenceCollision
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


def test_ensure_conversation_roundtrips_retrieval_scope(store):
    thread_id = _uuid()
    scope = {"documents": ["kb_1"], "max_chunks": 5, "nested": {"a": True}}
    r1 = store.ensure_conversation(thread_id, "u_1", "chat", "T", retrieval_scope=scope)
    assert r1["retrieval_scope"] == scope
    # get_conversation 回读同样内容
    got = store.get_conversation(thread_id, "u_1")
    assert got["retrieval_scope"] == scope


def test_ensure_conversation_scope_preserved_on_reuse(store):
    thread_id = _uuid()
    scope = {"documents": ["kb_1"]}
    store.ensure_conversation(thread_id, "u_1", "chat", "T", retrieval_scope=scope)
    # 复用时不传 scope，不应清空已存 scope
    r2 = store.ensure_conversation(thread_id, "u_1", "chat", "T2")
    assert r2["retrieval_scope"] == scope


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
    """模拟并发 MAX+1 撞车：第一次 insert_turn 抛序列冲突，重试后成功。"""

    def __init__(self):
        super().__init__()
        self._inserted = 0

    def insert_turn(self, turn_id, thread_id, user_id, sequence_no):
        self._inserted += 1
        if self._inserted == 1:
            raise SequenceCollision("boom")
        return super().insert_turn(turn_id, thread_id, user_id, sequence_no)


def test_next_turn_retries_on_unique_conflict():
    db = _RacyDb()
    store = ConversationStore(db)
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    assert turn["sequence_no"] == 1
    assert db._inserted == 2  # 第一次撞车，重试成功


def test_next_turn_propagates_non_collision_errors():
    db = FakeConversationDb()
    store = ConversationStore(db)
    store.ensure_conversation("t-1", "u_1", "chat", "T")

    def boom(turn_id, thread_id, user_id, sequence_no):
        raise RuntimeError("db down")

    db.insert_turn = boom
    with pytest.raises(RuntimeError, match="db down"):
        store.next_turn("t-1", "u_1")


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


def test_set_message_status_clears_completed_at_on_non_completed(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "stream", _uuid(), None)

    completed = store.set_message_status("u_1", msg["id"], "completed")
    assert completed["completed_at"] is not None

    # completed → failed 应清空 completed_at
    failed = store.set_message_status("u_1", msg["id"], "failed")
    assert failed["status"] == "failed"
    assert failed["completed_at"] is None

    # completed → cancelled 同样清空
    store.set_message_status("u_1", msg["id"], "completed")
    cancelled = store.set_message_status("u_1", msg["id"], "cancelled")
    assert cancelled["status"] == "cancelled"
    assert cancelled["completed_at"] is None


def test_set_message_status_rejects_wrong_owner(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "stream", _uuid(), None)
    with pytest.raises(OwnershipError):
        store.set_message_status("u_2", msg["id"], "completed")


def test_set_message_content_metadata_roundtrip(store):
    """set_message_content 携带 metadata 富结构写入，None 时保持既有值。"""
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "in-progress", _uuid(), None)
    # 首次写入 metadata
    updated = store.set_message_content("u_1", msg["id"], "done", metadata={"sources": [{"doc": "d"}]})
    assert updated["metadata"] == {"sources": [{"doc": "d"}]}
    # 再次写入（content 更新）不传 metadata → metadata 保持不变
    updated2 = store.set_message_content("u_1", msg["id"], "done2")
    assert updated2["metadata"] == {"sources": [{"doc": "d"}]}


def test_set_message_content_rejects_wrong_owner(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "s", _uuid(), None)
    with pytest.raises(OwnershipError):
        store.set_message_content("u_2", msg["id"], "x")


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


def test_start_run_status_param(store):
    """start_run(status=...) 直接以给定状态插入 run（无需 finish_run 兜底转 streaming）。"""
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)
    run = store.start_run(
        thread_id=turn["thread_id"], turn_id=turn["id"], message_id=msg["id"],
        user_id="u_1", module="chat", agent_id="a", model="m",
        status="streaming",
    )
    assert run["status"] == "streaming"
    assert run["finished_at"] is None  # streaming 非终态，不写 finished_at


def test_start_run_default_pending(store):
    """start_run 缺省 status 仍为 pending（向后兼容既有调用方）。"""
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)
    run = store.start_run(
        thread_id=turn["thread_id"], turn_id=turn["id"], message_id=msg["id"],
        user_id="u_1", module="chat", agent_id="a", model="m",
    )
    assert run["status"] == "pending"


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


# ── rename title ──


def test_rename_title_updates_conversation(store):
    store.ensure_conversation("t-1", "u_1", "chat", "Old")
    updated = store.rename_title("t-1", "u_1", "New Title")
    assert updated["title"] == "New Title"
    assert store.get_conversation("t-1", "u_1")["title"] == "New Title"


def test_rename_title_by_uuid(store):
    conv = store.ensure_conversation("t-1", "u_1", "chat", "Old")
    updated = store.rename_title(conv["id"], "u_1", "ByUUID")
    assert updated["title"] == "ByUUID"


def test_rename_title_rejects_wrong_owner(store):
    store.ensure_conversation("t-1", "u_1", "chat", "Old")
    with pytest.raises(OwnershipError):
        store.rename_title("t-1", "u_2", "Hijack")


def test_rename_title_missing_raises(store):
    with pytest.raises(OwnershipError):
        store.rename_title("t-none", "u_1", "X")


# ── clear (保留 conversation / 删 messages+turns) ──


def test_clear_keeps_conversation_removes_messages_and_turns(store):
    store.ensure_conversation("t-1", "u_1", "chat", "Title")
    t1 = store.next_turn("t-1", "u_1")
    store.add_user_message(t1["id"], t1["thread_id"], "u_1", "q1", "completed")
    store.add_assistant_message(t1["id"], t1["thread_id"], "u_1", "a1", _uuid(), None)
    t2 = store.next_turn("t-1", "u_1")
    store.add_user_message(t2["id"], t2["thread_id"], "u_1", "q2", "completed")

    n = store.clear_conversation("t-1", "u_1")
    assert n == 2  # 删除两个 turn（消息随之清理）
    conv = store.get_conversation("t-1", "u_1")
    assert conv is not None
    assert conv["title"] == "Title"
    assert store.list_messages("t-1", "u_1") == []


def test_clear_removes_messages_unreachable_by_run(store):
    # clear 后消息/run 清空，但 conversation 仍在
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)
    store.start_run(
        thread_id=turn["thread_id"], turn_id=turn["id"], message_id=msg["id"],
        user_id="u_1", module="chat", agent_id="a", model="m",
    )
    store.clear_conversation("t-1", "u_1")
    assert store.list_messages("t-1", "u_1") == []
    assert store.get_conversation("t-1", "u_1") is not None


def test_clear_rejects_wrong_owner(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    with pytest.raises(OwnershipError):
        store.clear_conversation("t-1", "u_2")


# ── delete conversation ──


def test_delete_conversation_removes_row_and_children(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    store.add_user_message(turn["id"], turn["thread_id"], "u_1", "q", "completed")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)
    run = store.start_run(
        thread_id=turn["thread_id"], turn_id=turn["id"], message_id=msg["id"],
        user_id="u_1", module="chat", agent_id="a", model="m",
    )
    store.add_retrieval(user_id="u_1", run_id=run["id"], query_index=0)
    store.add_tool_call(user_id="u_1", run_id=run["id"], tool_name="x", status="ok")

    deleted = store.delete_conversation("t-1", "u_1")
    assert deleted is True
    assert store.get_conversation("t-1", "u_1") is None
    with pytest.raises(OwnershipError):
        store.list_messages("t-1", "u_1")


def test_delete_conversation_by_uuid(store):
    conv = store.ensure_conversation("t-1", "u_1", "chat", "T")
    assert store.delete_conversation(conv["id"], "u_1") is True
    assert store.get_conversation("t-1", "u_1") is None


def test_delete_conversation_rejects_wrong_owner(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    with pytest.raises(OwnershipError):
        store.delete_conversation("t-1", "u_2")


def test_delete_conversation_missing_raises(store):
    with pytest.raises(OwnershipError):
        store.delete_conversation("t-none", "u_1")


def test_clear_removes_orphaned_regeneration_keys(store):
    """clear 删除受影响 messages 的 regeneration_keys（避免悬挂 idempotency 键）。"""
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)

    # 同 message 的幂等键 + 他人/他消息的幂等键（不得误删）
    store.complete_regeneration("u_1", "key-hit-1", msg["id"])
    store.complete_regeneration("u_1", "key-hit-2", msg["id"])
    # 预留中（message_id=None）的键：不属于任何 message，不受 thread 清理影响
    assert store.reserve_regeneration("u_1", "key-reserved") == ("reserved", None)
    # 他人同名键（不同 message）不得被清
    t2 = store.next_turn("t-1", "u_1")
    m2 = store.add_assistant_message(t2["id"], t2["thread_id"], "u_1", "b", None, None)
    store.complete_regeneration("u_1", "key-other-msg", m2["id"])

    store.clear_conversation("t-1", "u_1")

    assert store.get_regeneration("u_1", "key-hit-1") is None
    assert store.get_regeneration("u_1", "key-hit-2") is None
    # 预留中（message_id=None）的键不受 thread 作用域删除影响
    assert store.reserve_regeneration("u_1", "key-reserved") == ("exists", None)


def test_delete_removes_orphaned_regeneration_keys(store):
    """delete 同样清理受影响 messages 的 regeneration_keys。"""
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)
    store.complete_regeneration("u_1", "key-del", msg["id"])
    store.delete_conversation("t-1", "u_1")
    assert store.get_regeneration("u_1", "key-del") is None


# ── list runs ──


def test_list_runs_returns_thread_runs_ordered(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)
    r1 = store.start_run(
        thread_id=turn["thread_id"], turn_id=turn["id"], message_id=msg["id"],
        user_id="u_1", module="chat", agent_id="a", model="m",
        prompt_version="sha256:abc", agent_version="1",
    )
    store.finish_run(user_id="u_1", run_id=r1["id"], status="completed", latency_ms=100)
    r2 = store.start_run(
        thread_id=turn["thread_id"], turn_id=turn["id"], message_id=msg["id"],
        user_id="u_1", module="chat", agent_id="a", model="m",
        prompt_version="sha256:def", agent_version="2",
    )

    runs = store.list_runs("t-1", "u_1")
    ids = [r["id"] for r in runs]
    assert ids == [r1["id"], r2["id"]]
    assert {r["prompt_version"] for r in runs} == {"sha256:abc", "sha256:def"}


def test_list_runs_empty(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    assert store.list_runs("t-1", "u_1") == []


def test_list_runs_rejects_wrong_owner(store):
    store.ensure_conversation("t-1", "u_1", "chat", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_assistant_message(turn["id"], turn["thread_id"], "u_1", "a", None, None)
    store.start_run(
        thread_id=turn["thread_id"], turn_id=turn["id"], message_id=msg["id"],
        user_id="u_1", module="chat", agent_id="a", model="m",
    )
    with pytest.raises(OwnershipError):
        store.list_runs("t-1", "u_2")
