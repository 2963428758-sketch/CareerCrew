"""新 memory_records 仓储与旧数据回填的安全边界。"""
from __future__ import annotations

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.records import LongTermMemoryRepository, build_legacy_backfill


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
