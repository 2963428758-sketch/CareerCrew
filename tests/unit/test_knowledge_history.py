"""知识库多轮上下文：从 episodic 恢复历史对话测试。"""
from __future__ import annotations

from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry


def _rt_with_history() -> tuple[CareerCrewRuntime, FakeMemoryDb]:
    rt = CareerCrewRuntime()
    db = FakeMemoryDb()
    rt.memory_db = db
    ep = EpisodicMemory(db, user_id="u1", thread_id="k-t1")
    ep.write(MemoryEntry(type="user_message", content="LangChain 是什么"))
    ep.write(MemoryEntry(type="agent_response", content="LangChain 是一个框架。"))
    ep.write(MemoryEntry(type="user_message", content="它和 LangGraph 什么关系"))
    ep.write(MemoryEntry(
        type="agent_response",
        content={"text": "LangGraph 是编排层。", "sources": [{"doc": "n"}]},
    ))
    # 干扰项：其他类型不参与上下文
    ep.write(MemoryEntry(type="note", content="无关备注"))
    return rt, db


def test_thread_history_restores_messages() -> None:
    rt, _ = _rt_with_history()
    msgs = rt._thread_history_messages("u1", "k-t1")
    assert len(msgs) == 4  # 4 条对话消息（note 被过滤）
    assert msgs[0].content == "LangChain 是什么"
    assert msgs[1].content == "LangChain 是一个框架。"
    assert msgs[3].content == "LangGraph 是编排层。"  # dict content 取 text


def test_thread_history_truncates_to_recent_rounds() -> None:
    rt, _ = _rt_with_history()
    msgs = rt._thread_history_messages("u1", "k-t1", max_rounds=1)
    assert len(msgs) == 2  # 只保留最近一轮
    assert msgs[0].content == "它和 LangGraph 什么关系"


def test_thread_history_empty() -> None:
    rt = CareerCrewRuntime()
    rt.memory_db = FakeMemoryDb()
    assert rt._thread_history_messages("u1", "no-such") == []


def test_thread_history_excludes_pending_user_entry() -> None:
    """刚写入的当前用户消息（pending_user_entry_id）不进入历史上下文，避免重复。"""
    rt, db = _rt_with_history()
    ep = EpisodicMemory(db, user_id="u1", thread_id="k-t1")
    pending = ep.write(MemoryEntry(type="user_message", content="刚问的新问题"))
    msgs = rt._thread_history_messages(
        "u1", "k-t1", exclude_entry_id=pending.id
    )
    assert len(msgs) == 4  # 4 条旧对话，不含刚写入的当前问题
    assert all(m.content != "刚问的新问题" for m in msgs)
    # 不排除时该条会出现（恢复视图用）
    all_msgs = rt._thread_history_messages("u1", "k-t1")
    assert any(m.content == "刚问的新问题" for m in all_msgs)


def test_record_user_message_persists_before_run() -> None:
    """record_user_message 立即落库用户消息并登记线程，不等待 agent 完成。"""
    from careercrew_core.memory.threads import ThreadStore

    rt = CareerCrewRuntime()
    rt._initialized = True  # 跳过重组件初始化，只测记忆层
    db = FakeMemoryDb()
    rt.memory_db = db
    rt.thread_store = ThreadStore(db, user_id="u1")
    entry_id = rt.record_user_message("u1", "k-t1", "我有什么项目", module="knowledge")
    assert entry_id
    rows = db.list_episodic("u1", thread_id="k-t1")
    assert len(rows) == 1
    assert rows[0]["type"] == "user_message"
    assert rows[0]["content"] == "我有什么项目"
    thread = db.get_thread("u1", "k-t1")
    assert thread is not None
    assert thread["module"] == "knowledge"
    assert thread["title"] == "我有什么项目"
