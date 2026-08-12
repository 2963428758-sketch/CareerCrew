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
