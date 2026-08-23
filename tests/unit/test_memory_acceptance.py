"""长期记忆实施计划的关键验收案例。"""
from __future__ import annotations

import pytest

from careercrew_core.memory.candidates import extract_candidates
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.policy import MemoryPolicyStore
from careercrew_core.memory.service import MemoryPolicyDenied, MemoryService
from careercrew_core.memory.vector_outbox import drain_vector_outbox


def _service(*, enabled=True, generate=True, use=True):
    db = FakeMemoryDb()
    policies = MemoryPolicyStore(db)
    policies.set_global(True, True, True)
    policies.set_user("u1", enabled, generate, use)
    return MemoryService(db, policy_store=policies, feature_enabled=True), db


def test_acceptance_1_to_4_stable_fact_negative_rules_and_explicit_save():
    service, _ = _service()
    assert service.capture_text_candidates("u1", "我有 3 年 Java 后端经验")[0].name == "profile.experience_years"
    assert extract_candidates("Java 的 HashMap 是什么") == []
    assert extract_candidates("我想看看西雅图天气") == []
    assert service.save_explicit("u1", name="preferences.work_mode", value="远程").source == "explicit"


def test_acceptance_5_and_10_supersede_and_multilingual_dedup():
    service, _ = _service()
    service.capture_text_candidates("u1", "我想转向 Backend Engineer")
    service.capture_text_candidates("u1", "我想转向 AI Engineer")
    service.capture_text_candidates("u1", "以后只考虑 Remote 工作")
    service.capture_text_candidates("u1", "以后只考虑远程工作")

    active = service.records.list_active("u1")
    assert len([r for r in active if r["normalized_key"] == "semantic:profile.direction"]) == 1
    mode = next(r for r in active if r["normalized_key"] == "semantic:preferences.work_mode")
    assert len(service.records.list_sources(mode["id"])) == 2


def test_acceptance_6_to_9_policy_tool_boundary_and_deletion():
    disabled, db = _service(enabled=False)
    with pytest.raises(MemoryPolicyDenied):
        disabled.capture_text_candidates("u1", "我有 3 年 Java 后端经验")
    assert db.list_facts("u1") == [] and db.list_episodic("u1") == []

    no_use, _ = _service(use=False)
    no_use.save_explicit("u1", name="preferences.work_mode", value="远程")
    assert no_use.search("u1", "远程") == []

    service, _ = _service()
    service.save_explicit("u1", name="preferences.work_mode", value="远程")
    record = service.records.list_active("u1")[0]
    assert service.delete("u1", kind="fact", record_id=record["id"]) == 1
    assert service.search("u1", "远程") == []

    class Indexer:
        def upsert_memory(self, _record): pass
        def delete_memory(self, _memory_id): pass
    assert drain_vector_outbox(service.records, Indexer())["failed"] == 0
