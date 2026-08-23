"""新 memory_records 仓储与旧数据回填的安全边界。"""
from __future__ import annotations

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.records import LongTermMemoryRepository, build_legacy_backfill
from careercrew_core.memory.vector_outbox import (
    MemoryRecordVectorIndexer, drain_vector_outbox, reconcile_vector_ids,
)


def test_backfill_dry_run_excludes_transcripts_and_is_idempotent() -> None:
    db = FakeMemoryDb()
    db.upsert_fact("u1", "profile.direction", "profile", "目标", {"direction": "AI"}, "form", 1)
    db.insert_episodic("u1", "t1", "chat", None, "user_message", "不要回填", "2026-08-01T00:00:00+00:00")
    db.insert_episodic("u1", "t1", "offer-1", None, "offer", {"company": "OpenAI"}, "2026-08-02T00:00:00+00:00")

    report = build_legacy_backfill(db, ["u1"])

    assert report.summary() == {
        "scanned_facts": 1, "scanned_events": 2, "skipped_transcripts": 1,
        "skipped_invalid": 0, "candidates": 2,
    }
    repo = LongTermMemoryRepository(db)
    assert repo.apply_backfill(report)["created"] == 2
    assert repo.apply_backfill(report)["existing"] == 2
    assert {record["category"] for record in repo.list_active("u1")} == {"profile", "offer"}


def test_backfill_uses_user_scope_for_same_legacy_name() -> None:
    db = FakeMemoryDb()
    db.upsert_fact("u1", "profile.direction", "profile", "方向", {"direction": "AI"}, "form", 1)
    db.upsert_fact("u2", "profile.direction", "profile", "方向", {"direction": "Java"}, "form", 1)

    repo = LongTermMemoryRepository(db)
    repo.apply_backfill(build_legacy_backfill(db, ["u1", "u2"]))

    assert len(repo.list_active("u1")) == 1
    assert len(repo.list_active("u2")) == 1


def test_changed_fact_supersedes_and_same_fact_accumulates_sources() -> None:
    db = FakeMemoryDb()
    db.upsert_fact("u1", "profile.direction", "profile", "方向", {"direction": "Java"}, "form", 1)
    repo = LongTermMemoryRepository(db)
    first_report = build_legacy_backfill(db, ["u1"])
    first, created = repo.upsert(first_report.candidates[0])
    again, created_again = repo.upsert(first_report.candidates[0])

    db.upsert_fact("u1", "profile.direction", "profile", "方向", {"direction": "AI"}, "form", 1)
    changed = build_legacy_backfill(db, ["u1"]).candidates[0]
    current, changed_created = repo.upsert(changed)

    assert created and not created_again and again["id"] == first["id"]
    assert len(repo.list_sources(first["id"])) == 2
    assert changed_created and current["id"] != first["id"]
    assert repo.list_relations(current["id"])[0]["relation_type"] == "supersedes"
    assert len(repo.list_active("u1")) == 1


def test_outbox_retries_and_soft_delete_are_vector_safe() -> None:
    class Indexer:
        def __init__(self): self.upserted, self.deleted = [], []
        def upsert_memory(self, record): self.upserted.append(record["id"])
        def delete_memory(self, memory_id): self.deleted.append(memory_id)

    db = FakeMemoryDb()
    db.upsert_fact("u1", "profile.direction", "profile", "方向", {"direction": "AI"}, "form", 1)
    repo = LongTermMemoryRepository(db)
    record, _ = repo.upsert(build_legacy_backfill(db, ["u1"]).candidates[0])
    indexer = Indexer()

    assert drain_vector_outbox(repo, indexer) == {"processed": 1, "failed": 0}
    assert indexer.upserted == [record["id"]]
    assert repo.soft_delete("u1", record["id"])
    assert drain_vector_outbox(repo, indexer) == {"processed": 1, "failed": 0}
    assert indexer.deleted == [record["id"]]
    assert reconcile_vector_ids({"a", "b"}, {"b", "c"}) == {"missing": ["a"], "orphaned": ["c"]}


def test_real_indexer_converts_record_to_tenant_scoped_vector_record() -> None:
    class Embedding:
        def encode(self, _texts):
            return type("Output", (), {"dense": [[0.1, 0.2]], "sparse": None})()
    class Store:
        def __init__(self): self.records = []
        def upsert(self, records): self.records.extend(records)
        def delete_by_metadata(self, filters): self.deleted = filters

    store = Store()
    indexer = MemoryRecordVectorIndexer(Embedding(), store)
    indexer.upsert_memory({"id": "m1", "user_id": "u1", "memory_type": "semantic", "category": "profile", "display_text": "AI"})
    indexer.delete_memory("m1")

    assert store.records[0].metadata["user_id"] == "u1"
    assert store.deleted == {"memory_id": "m1"}
