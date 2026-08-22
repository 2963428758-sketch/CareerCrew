"""自动注入（读路径通道一）测试。"""
from __future__ import annotations

from datetime import UTC

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.injection import MemoryInjector
from careercrew_core.memory.policy import MemoryPolicyStore
from careercrew_core.memory.router import MemoryRouter
from careercrew_core.memory.semantic import SemanticFactStore
from careercrew_core.memory.types import MemoryEntry


def _injector(feature_enabled: bool = True) -> tuple[MemoryInjector, MemoryPolicyStore]:
    db = FakeMemoryDb()
    facts = SemanticFactStore(db, user_id="u1")
    facts.upsert_fact("profile.skills", "profile", {"skills": ["Python", "RAG"]},
                      description="技能 Python/RAG", source="test")
    policy = MemoryPolicyStore(db)
    policy.set_global(enabled=True)
    policy.set_user("u1", enabled=True)
    em = EpisodicMemory(db, user_id="u1", thread_id="t1")
    em.write(MemoryEntry(type="interview_qa", content={"q": "RAG 怎么减幻觉", "score": 8}))
    inj = MemoryInjector(
        db=db, policy_store=policy, router=MemoryRouter(),
        episodic=em, feature_enabled=feature_enabled,
    )
    return inj, policy


def test_disabled_returns_none() -> None:
    inj, _ = _injector(feature_enabled=False)
    assert inj.build("u1", "帮我找工作") is None


def test_user_policy_off_returns_none() -> None:
    inj, policy = _injector()
    policy.set_user("u1", enabled=False)
    assert inj.build("u1", "帮我找工作") is None


def test_build_includes_profile_and_facts() -> None:
    inj, _ = _injector()
    out = inj.build("u1", "我的技能是 Python RAG，帮我找工作")
    assert out is not None
    assert "用户画像" in out
    assert "Python" in out
    assert "技能 Python/RAG" in out


def test_freshness_note_on_old_fact() -> None:
    db = FakeMemoryDb()
    facts = SemanticFactStore(db, user_id="u1")
    facts.upsert_fact(
        "profile.skills", "profile", {"skills": ["Java"]},
        description="技能 Java", source="t",
    )
    # 手动把 modified_at 改到 10 天前
    from datetime import datetime, timedelta

    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    db._facts[("u1", "profile.skills")]["modified_at"] = old
    policy = MemoryPolicyStore(db)
    policy.set_global(enabled=True)
    policy.set_user("u1", enabled=True)
    inj = MemoryInjector(
        db=db, policy_store=policy, router=MemoryRouter(),
        feature_enabled=True,
    )
    out = inj.build("u1", "技能")
    assert out is not None
    assert "10 天前写入" in out
