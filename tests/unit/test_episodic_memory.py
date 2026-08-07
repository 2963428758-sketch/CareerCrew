"""C2/C3 episodic 记忆 append-only 树 + 回溯重建测试。"""
from __future__ import annotations

from pathlib import Path

from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry


def test_write_auto_id_and_parentid_chain(tmp_path: Path) -> None:
    em = EpisodicMemory(tmp_path / "t.jsonl")
    e1 = em.write(MemoryEntry(type="session_start", content="start"))
    e2 = em.write(MemoryEntry(type="job_match", content={"company": "字节"}))
    e3 = em.write(MemoryEntry(type="application", content={"company": "字节", "status": "submitted"}))
    assert e1.id == "e_001" and e1.parentId is None
    assert e2.id == "e_002" and e2.parentId == "e_001"
    assert e3.id == "e_003" and e3.parentId == "e_002"
    assert em.latest().id == "e_003"


def test_append_only_history_unchanged(tmp_path: Path) -> None:
    em = EpisodicMemory(tmp_path / "t.jsonl")
    em.write(MemoryEntry(type="session_start", content="start"))
    em.write(MemoryEntry(type="note", content="a"))
    snapshot = (tmp_path / "t.jsonl").read_text(encoding="utf-8")
    em.write(MemoryEntry(type="note", content="b"))
    # 前两条不变（append-only）
    assert snapshot in (tmp_path / "t.jsonl").read_text(encoding="utf-8")


def test_get_and_children_with_fork(tmp_path: Path) -> None:
    em = EpisodicMemory(tmp_path / "t.jsonl")
    e1 = em.write(MemoryEntry(type="session_start", content="s"))
    e2 = em.write(MemoryEntry(type="note", content="c1"))  # parentId 自动接 e1
    e3 = em.write(MemoryEntry(type="note", content="c2", parentId=e1.id))  # 显式分叉到 e1
    assert em.get(e2.id).content == "c1"
    children = em.children(e1.id)
    assert {c.id for c in children} == {e2.id, e3.id}


def test_rebuild_context_root_to_leaf(tmp_path: Path) -> None:
    em = EpisodicMemory(tmp_path / "t.jsonl")
    e1 = em.write(MemoryEntry(type="session_start", content="root"))
    e2 = em.write(MemoryEntry(type="interview_qa", content={"q": "q1", "a": "a1"}))
    e3 = em.write(MemoryEntry(type="note", content="leaf"))
    chain = em.rebuild_context(e3.id)
    assert [e.id for e in chain] == [e1.id, e2.id, e3.id]
    assert chain[0].parentId is None
    assert chain[-1].id == e3.id


def test_rebuild_context_handles_missing_leaf(tmp_path: Path) -> None:
    em = EpisodicMemory(tmp_path / "t.jsonl")
    em.write(MemoryEntry(type="session_start", content="s"))
    assert em.rebuild_context("nonexistent") == []


def test_build_tree(tmp_path: Path) -> None:
    em = EpisodicMemory(tmp_path / "t.jsonl")
    e1 = em.write(MemoryEntry(type="session_start", content="root"))
    em.write(MemoryEntry(type="note", content="c1"))
    root = em.build_tree()
    assert root is not None
    assert root.entry.id == e1.id
    assert len(root.children) == 1
