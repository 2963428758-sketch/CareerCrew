"""episodic 记忆 append-only 树 + 回溯重建测试（FakeMemoryDb 后端）。"""
from __future__ import annotations

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry


def _em(user_id: str = "u1", thread_id: str = "t1") -> EpisodicMemory:
    return EpisodicMemory(FakeMemoryDb(), user_id=user_id, thread_id=thread_id)


def test_write_auto_id_and_parentid_chain() -> None:
    em = _em()
    e1 = em.write(MemoryEntry(type="session_start", content="start"))
    e2 = em.write(MemoryEntry(type="job_match", content={"company": "字节"}))
    e3 = em.write(MemoryEntry(type="application", content={"company": "字节", "status": "submitted"}))
    assert e1.id == "e_001" and e1.parentId is None
    assert e2.id == "e_002" and e2.parentId == "e_001"
    assert e3.id == "e_003" and e3.parentId == "e_002"
    assert em.latest().id == "e_003"


def test_append_only_history_unchanged() -> None:
    em = _em()
    em.write(MemoryEntry(type="session_start", content="start"))
    em.write(MemoryEntry(type="note", content="a"))
    snapshot = [e.model_dump() for e in em._read_all()]
    em.write(MemoryEntry(type="note", content="b"))
    # 前两条不变（append-only）
    assert snapshot == [e.model_dump() for e in em._read_all()][:2]


def test_get_and_children_with_fork() -> None:
    em = _em()
    e1 = em.write(MemoryEntry(type="session_start", content="s"))
    e2 = em.write(MemoryEntry(type="note", content="c1"))  # parentId 自动接 e1
    e3 = em.write(MemoryEntry(type="note", content="c2", parentId=e1.id))  # 显式分叉到 e1
    assert em.get(e2.id).content == "c1"
    children = em.children(e1.id)
    assert {c.id for c in children} == {e2.id, e3.id}


def test_rebuild_context_root_to_leaf() -> None:
    em = _em()
    e1 = em.write(MemoryEntry(type="session_start", content="root"))
    e2 = em.write(MemoryEntry(type="interview_qa", content={"q": "q1", "a": "a1"}))
    e3 = em.write(MemoryEntry(type="note", content="leaf"))
    chain = em.rebuild_context(e3.id)
    assert [e.id for e in chain] == [e1.id, e2.id, e3.id]
    assert chain[0].parentId is None
    assert chain[-1].id == e3.id


def test_rebuild_context_handles_missing_leaf() -> None:
    em = _em()
    em.write(MemoryEntry(type="session_start", content="s"))
    assert em.rebuild_context("nonexistent") == []


def test_build_tree() -> None:
    em = _em()
    e1 = em.write(MemoryEntry(type="session_start", content="root"))
    em.write(MemoryEntry(type="note", content="c1"))
    root = em.build_tree()
    assert root is not None
    assert root.entry.id == e1.id
    assert len(root.children) == 1


def test_user_isolation() -> None:
    db = FakeMemoryDb()
    em1 = EpisodicMemory(db, user_id="u1", thread_id="t1")
    em2 = EpisodicMemory(db, user_id="u2", thread_id="t1")
    em1.write(MemoryEntry(type="note", content="u1 的"))
    em2.write(MemoryEntry(type="note", content="u2 的"))
    assert len(em1._read_all()) == 1
    assert len(em2._read_all()) == 1
    assert em1._read_all()[0].content == "u1 的"
