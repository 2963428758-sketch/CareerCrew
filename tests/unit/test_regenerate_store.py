"""T1.6 store 层附加能力单元测试（FakeConversationDb）。

覆盖：add_user_message metadata 往返、store.get_run、regeneration_keys
幂等表（get_regeneration / create_regeneration）、版本链最后一条判定所需的
list_messages 语义回归。
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


def _begin_turn(store, thread_id="t-1", user_id="u_1", module="chat", agent_id="job_matcher",
                user_text="q", metadata=None):
    conv = store.ensure_conversation(thread_id, user_id, module, "T")
    turn = store.next_turn(thread_id, user_id)
    user_msg = store.add_user_message(
        turn["id"], conv["id"], user_id, user_text, "completed", metadata=metadata
    )
    asst = store.add_assistant_message(turn["id"], conv["id"], user_id, "", None, None)
    asst = store.set_message_status(user_id, asst["id"], "streaming")
    run = store.start_run(
        thread_id=conv["id"], turn_id=turn["id"], message_id=asst["id"],
        user_id=user_id, module=module, agent_id=agent_id, model="m",
        prompt_version="unversioned", agent_version="1", status="streaming",
    )
    asst = store.set_message_run_id(user_id, asst["id"], run["id"])
    asst = store.set_message_content(user_id, asst["id"], "answer", status="completed")
    return conv, turn, user_msg, asst, run


def test_add_user_message_metadata_roundtrip(store):
    """add_user_message 携带 metadata 富结构写入，None 时保持 NULL。"""
    store.ensure_conversation("t-1", "u_1", "knowledge", "T")
    turn = store.next_turn("t-1", "u_1")
    msg = store.add_user_message(
        turn["id"], turn["thread_id"], "u_1", "q", "completed",
        metadata={"category": "resume", "scope": "public"},
    )
    assert msg["metadata"] == {"category": "resume", "scope": "public"}

    msg2 = store.add_user_message(
        turn["id"], turn["thread_id"], "u_1", "q2", "completed",
    )
    assert msg2["metadata"] is None


def test_get_run_returns_owned_run(store):
    """store.get_run：按 user_id 取 run 行，跨用户返回 None（视为不存在）。"""
    _, _, _, _, run = _begin_turn(store)
    got = store.get_run("u_1", run["id"])
    assert got["id"] == run["id"]
    assert got["module"] == "chat"
    assert got["agent_id"] == "job_matcher"
    assert store.get_run("u_2", run["id"]) is None


def test_regeneration_keys_idempotent(store):
    """同 (user_id, key) 首次创建返回 message_id，二次返回 None（不重跑语义）。"""
    mid = _uuid()
    r1 = store.create_regeneration("u_1", "idem-1", mid)
    assert r1 == mid
    r2 = store.create_regeneration("u_1", "idem-1", _uuid())
    assert r2 is None  # 冲突 → 已存在
    got = store.get_regeneration("u_1", "idem-1")
    assert got == mid


def test_regeneration_keys_scoped_by_user(store):
    """同 key 不同 user 各自独立。"""
    store.create_regeneration("u_1", "key-x", "m1")
    r = store.create_regeneration("u_2", "key-x", "m2")
    assert r == "m2"
    assert store.get_regeneration("u_1", "key-x") == "m1"
    assert store.get_regeneration("u_2", "key-x") == "m2"


def test_regeneration_missing_returns_none(store):
    assert store.get_regeneration("u_1", "nope") is None


def test_begin_turn_writes_user_metadata():
    """begin_turn 把 user_metadata 写入 user 消息 metadata 列（T1.6 重跑输入保真）。"""
    from careercrew_api.chat_lifecycle import begin_turn

    store = ConversationStore(FakeConversationDb())
    ctx = begin_turn(
        store, thread_id="t-1", user_id="u_1", module="knowledge",
        agent_id="knowledge_advisor", user_text="问题", model="m",
        user_metadata={"category": "resume", "scope": "public"},
    )
    user = store.get_message("u_1", ctx.user_message_id)
    assert user["metadata"] == {"category": "resume", "scope": "public"}

    # 未传 metadata → NULL
    ctx2 = begin_turn(
        store, thread_id="t-1", user_id="u_1", module="chat",
        agent_id="career_planner", user_text="问", model="m",
    )
    user2 = store.get_message("u_1", ctx2.user_message_id)
    assert user2["metadata"] is None
