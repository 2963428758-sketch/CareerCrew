from __future__ import annotations

from careercrew_core.memory.candidates import extract_candidates
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.policy import MemoryPolicyStore
from careercrew_core.memory.service import MemoryService


def _service() -> MemoryService:
    db = FakeMemoryDb()
    policy = MemoryPolicyStore(db)
    policy.set_global(True, True, True)
    policy.set_user("u1", True, True, True)
    return MemoryService(db, policy_store=policy, feature_enabled=True)


def test_generic_qa_and_weather_never_become_candidates() -> None:
    assert extract_candidates("Java 的 HashMap 是什么") == []
    assert extract_candidates("我想看看西雅图天气") == []


def test_stable_experience_and_explicit_preference_are_structured() -> None:
    assert extract_candidates("我有 3 年 Java 后端经验")[0].value == 3
    assert extract_candidates("以后只考虑 Remote 工作，记住这个")[0].value == "远程"


def test_capture_candidates_upserts_one_current_fact() -> None:
    service = _service()
    saved = service.capture_text_candidates("u1", "我有 3 年 Java 后端经验")
    repeated = service.capture_text_candidates("u1", "我有 3 年 Java 后端经验")

    assert [x.name for x in saved] == ["profile.experience_years"]
    assert [x.name for x in repeated] == ["profile.experience_years"]
    assert service.load_profile("u1").profile.experience_years == 3
