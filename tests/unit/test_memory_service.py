"""MemoryService 是长期记忆的唯一公共边界。"""
from __future__ import annotations

import pytest

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.policy import MemoryPolicyStore
from careercrew_core.memory.service import MemoryPolicyDenied, MemoryService


def _service(*, enabled: bool = True, generate: bool = True, use: bool = True) -> tuple[MemoryService, FakeMemoryDb]:
    db = FakeMemoryDb()
    policy = MemoryPolicyStore(db)
    policy.set_global(enabled=True, generate=True, use=True)
    policy.set_user("u1", enabled=enabled, generate=generate, use=use)
    return MemoryService(db, policy_store=policy, feature_enabled=True), db


def test_disabled_memory_rejects_every_write_path() -> None:
    service, db = _service(enabled=False)

    with pytest.raises(MemoryPolicyDenied):
        service.write_event("u1", "job_match", {"title": "Java 后端"})
    with pytest.raises(MemoryPolicyDenied):
        service.save_explicit("u1", name="preferences.work_mode", value="远程")
    with pytest.raises(MemoryPolicyDenied):
        service.update_profile("u1", {"profile.direction": "Java 后端"})

    assert db.list_episodic("u1") == []
    assert db.list_facts("u1") == []


def test_explicit_save_is_allowed_when_generation_is_off() -> None:
    service, _ = _service(generate=False)

    fact = service.save_explicit("u1", name="preferences.work_mode", value="远程")

    assert fact.name == "preferences.work_mode"
    assert fact.content == {"work_mode": "远程"}
    assert fact.source == "explicit"


def test_automatic_profile_update_requires_generate_permission() -> None:
    service, _ = _service(generate=False)

    with pytest.raises(MemoryPolicyDenied):
        service.update_profile("u1", {"profile.direction": "AI Engineer"})


def test_automatic_writer_rejects_untyped_note_to_prevent_chat_pollution() -> None:
    service, db = _service()

    with pytest.raises(ValueError, match="重要事件类型"):
        service.write_event("u1", "note", {"text": "顺便问一下 HashMap"})

    assert db.list_episodic("u1") == []


def test_same_normalized_fact_is_updated_instead_of_duplicated() -> None:
    service, db = _service()
    service.save_explicit("u1", name="preferences.work_mode", value="远程")
    updated = service.save_explicit("u1", name="preferences.work_mode", value="Remote")

    assert len(db.list_facts("u1")) == 1
    assert updated.version == 2


def test_memory_list_is_latest_first_and_never_returns_transcript_rows() -> None:
    service, db = _service()
    db.insert_episodic("u1", "t1", "old", None, "job_match", {"title": "旧岗位"}, "2026-08-01T00:00:00+00:00")
    db.insert_episodic("u1", "t1", "chat", None, "user_message", "不应显示", "2026-08-03T00:00:00+00:00")
    db.insert_episodic("u1", "t1", "new", None, "offer", {"company": "新公司"}, "2026-08-02T00:00:00+00:00")

    page = service.list_records("u1", limit=1)
    second = service.list_records("u1", limit=1, cursor=page["next_cursor"])

    assert page["total"] == 2
    assert [row["id"] for row in page["items"]] == ["new"]
    assert [row["id"] for row in second["items"]] == ["old"]


def test_delete_removes_the_matching_vector_point() -> None:
    class VectorSpy:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete_by_ids(self, ids: list[str]) -> int:
            self.deleted.extend(ids)
            return len(ids)

    service, db = _service()
    vector = VectorSpy()
    service._vector_store = vector
    db.insert_episodic("u1", "t1", "event-1", None, "offer", {"company": "OpenAI"}, "2026-08-03T00:00:00+00:00")

    removed = service.delete("u1", kind="event", entry_id="event-1")

    assert removed == 1
    assert vector.deleted == ["event-1"]


def test_service_mirrors_explicit_facts_with_source_lineage() -> None:
    service, _ = _service()

    service.save_explicit("u1", name="preferences.work_mode", value="远程")
    record = service.records.list_active("u1")[0]

    assert record["normalized_key"] == "semantic:preferences.work_mode"
    assert service.records.list_sources(record["id"])[0]["source_type"] == "explicit"


def test_new_active_records_win_over_legacy_projection_and_delete_is_soft() -> None:
    service, _ = _service()
    service.save_explicit("u1", name="preferences.work_mode", value="远程")
    record = service.records.list_active("u1")[0]

    page = service.list_records("u1")
    assert [row["id"] for row in page["items"]] == [record["id"]]
    assert service.delete("u1", kind="fact", record_id=record["id"]) == 1
    assert service.records.list_active("u1") == []
