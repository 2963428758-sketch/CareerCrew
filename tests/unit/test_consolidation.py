"""后台 consolidation 门控 + 四阶段测试。"""
from __future__ import annotations

from careercrew_core.memory.consolidation import Consolidator
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.semantic import SemanticFactStore
from careercrew_core.memory.types import MemoryEntry


def _db_with_events(n: int = 3) -> FakeMemoryDb:
    db = FakeMemoryDb()
    for i in range(n):
        em = EpisodicMemory(db, user_id="u1", thread_id=f"t{i}")
        em.write(MemoryEntry(
            type="interview_qa",
            content={"q": f"RAG 问题{i}", "score": 8 + i},
        ))
    return db


def test_gate_requires_min_sessions() -> None:
    db = _db_with_events(2)
    c = Consolidator(db, min_interval_hours=0, min_sessions=5)
    assert c.should_run("u1") is False
    assert c.consolidate("u1")["ran"] is False


def test_force_consolidate_updates_mastery_and_marker() -> None:
    db = _db_with_events(3)
    c = Consolidator(db, min_interval_hours=0, min_sessions=1)
    out = c.consolidate("u1", force=True)
    assert out["ran"] is True
    assert "prune" in out["phases"]
    facts = SemanticFactStore(db, user_id="u1")
    mastery = facts.get_fact("interview_mastery")
    assert mastery is not None
    assert len(mastery.content["mastery"]) >= 1
    marker = facts.get_fact("__consolidation__")
    assert marker is not None
    assert marker.content["last_consolidated_at"]


def test_prune_removes_stale_low_confidence() -> None:
    db = FakeMemoryDb()
    facts = SemanticFactStore(db, user_id="u1")
    facts.upsert_fact("preferences.city", "preference", {"city": ["旧城"]},
                      source="t", confidence=0.2)
    facts.upsert_fact("profile.skills", "profile", {"skills": ["Python"]},
                      source="t", confidence=0.9)
    c = Consolidator(db, min_interval_hours=0, min_sessions=1, stale_days=0)
    out = c.consolidate("u1", force=True)
    assert out["pruned"] >= 1
    assert facts.get_fact("preferences.city") is None
    assert facts.get_fact("profile.skills") is not None
