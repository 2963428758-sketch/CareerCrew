"""多轮上下文以 ConversationStore 为主，episodic 只兼容旧会话。"""
from __future__ import annotations

from careercrew_api.chat_lifecycle import begin_turn, finish_turn
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.conversation.db import FakeConversationDb
from careercrew_core.conversation.store import ConversationStore
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry


def _rt_with_history() -> tuple[CareerCrewRuntime, FakeMemoryDb]:
    rt = CareerCrewRuntime()
    rt._initialized = True
    rt.memory_db = FakeMemoryDb()
    rt.conversation_store = ConversationStore(FakeConversationDb())

    first = begin_turn(
        rt.conversation_store, thread_id="k-t1", user_id="u1", module="knowledge",
        agent_id="knowledge_advisor", user_text="LangChain 是什么", model="test",
    )
    finish_turn(rt.conversation_store, first, "LangChain 是一个框架。")
    second = begin_turn(
        rt.conversation_store, thread_id="k-t1", user_id="u1", module="knowledge",
        agent_id="knowledge_advisor", user_text="它和 LangGraph 什么关系", model="test",
    )
    finish_turn(
        rt.conversation_store, second, "LangGraph 是编排层。",
        metadata={"sources": [{"doc": "n"}]},
    )
    return rt, rt.memory_db


def test_thread_history_restores_messages_from_conversation() -> None:
    rt, _ = _rt_with_history()
    msgs = rt._thread_history_messages("u1", "k-t1")
    assert [m.content for m in msgs] == [
        "LangChain 是什么", "LangChain 是一个框架。",
        "它和 LangGraph 什么关系", "LangGraph 是编排层。",
    ]


def test_thread_history_truncates_to_recent_rounds() -> None:
    rt, _ = _rt_with_history()
    msgs = rt._thread_history_messages("u1", "k-t1", max_rounds=1)
    assert [m.content for m in msgs] == ["它和 LangGraph 什么关系", "LangGraph 是编排层。"]


def test_thread_history_empty() -> None:
    rt = CareerCrewRuntime()
    rt._initialized = True
    rt.memory_db = FakeMemoryDb()
    rt.conversation_store = ConversationStore(FakeConversationDb())
    assert rt._thread_history_messages("u1", "no-such") == []


def test_thread_history_excludes_current_conversation_message() -> None:
    rt, _ = _rt_with_history()
    pending = begin_turn(
        rt.conversation_store, thread_id="k-t1", user_id="u1", module="knowledge",
        agent_id="knowledge_advisor", user_text="刚问的新问题", model="test",
    )
    msgs = rt._thread_history_messages(
        "u1", "k-t1", exclude_entry_id=pending.user_message_id,
    )
    assert len(msgs) == 4
    assert all(m.content != "刚问的新问题" for m in msgs)


def test_legacy_episodic_transcript_is_read_only_fallback() -> None:
    rt = CareerCrewRuntime()
    rt._initialized = True
    db = FakeMemoryDb()
    rt.memory_db = db
    rt.conversation_store = ConversationStore(FakeConversationDb())
    ep = EpisodicMemory(db, user_id="u1", thread_id="legacy-t1")
    ep.write(MemoryEntry(type="user_message", content="旧问题"))
    ep.write(MemoryEntry(type="agent_response", content={"text": "旧回答"}))

    msgs = rt._thread_history_messages("u1", "legacy-t1")

    assert [m.content for m in msgs] == ["旧问题", "旧回答"]


def test_transcript_helpers_do_not_write_long_term_memory() -> None:
    rt, db = _rt_with_history()
    pending = begin_turn(
        rt.conversation_store, thread_id="k-t1", user_id="u1", module="knowledge",
        agent_id="knowledge_advisor", user_text="我有什么项目", model="test",
    )

    entry_id = rt.record_user_message("u1", "k-t1", "我有什么项目", module="knowledge")
    written = rt.record_thread_messages(
        "u1", "k-t1", "", "这里是项目列表", module="knowledge",
    )

    assert entry_id == pending.user_message_id
    assert written == 0
    assert db.list_episodic("u1", thread_id="k-t1") == []
