"""人工长期记忆治理的状态、审计和租户边界。"""
from __future__ import annotations

import pytest

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.governance import (
    MemoryConflictError,
    MemoryGovernance,
    MemoryNotFoundError,
    MemoryValidationError,
)
from careercrew_core.memory.records import BackfillItem, LongTermMemoryRepository


def _record(
    db: FakeMemoryDb,
    user_id: str,
    *,
    normalized_key: str = "semantic:profile.direction",
    display_text: str = "目标方向：Java",
    memory_type: str = "semantic",
) -> dict:
    repo = LongTermMemoryRepository(db)
    row, _created = repo.upsert(BackfillItem(
        user_id=user_id,
        memory_type=memory_type,
        category="profile" if memory_type == "semantic" else "offer",
        normalized_key=normalized_key,
        display_text=display_text,
        payload={"value": display_text},
        source_type="test",
        legacy_id=f"legacy-{user_id}-{normalized_key}",
    ))
    return row


def test_confirm_is_idempotent_in_identity_and_creates_a_safe_event() -> None:
    db = FakeMemoryDb()
    row = _record(db, "u1")
    governance = MemoryGovernance(db)

    confirmed = governance.apply_action(
        "u1", row["id"], action="confirm", expected_row_version=1,
        reason="用户核对无误",
    )

    assert confirmed["id"] == row["id"]
    assert confirmed["status"] == "active"
    assert confirmed["row_version"] == 2
    history = governance.history("u1", row["id"])
    assert [event["action"] for event in history["events"]] == ["confirm"]
    assert "display_text" not in history["events"][0]["before_snapshot"]


def test_edit_supersedes_old_record_and_keeps_one_active_value() -> None:
    db = FakeMemoryDb()
    row = _record(db, "u1")
    governance = MemoryGovernance(db)

    edited = governance.apply_action(
        "u1", row["id"], action="edit", expected_row_version=1,
        display_text="目标方向：Python",
        reason="用户修正",
    )

    assert edited["id"] != row["id"]
    assert edited["display_text"] == "目标方向：Python"
    assert edited["status"] == "active"
    assert governance.get("u1", row["id"])["status"] == "superseded"
    assert [item["id"] for item in governance.list_records("u1")] == [edited["id"]]
    assert any(item["relation_type"] == "supersedes" for item in governance.history("u1", edited["id"])["relations"])


@pytest.mark.parametrize("action", ["ignore", "expire"])
def test_ignore_and_expire_leave_default_list_but_remain_in_all_history(action: str) -> None:
    db = FakeMemoryDb()
    row = _record(db, "u1")
    governance = MemoryGovernance(db)

    changed = governance.apply_action(
        "u1", row["id"], action=action, expected_row_version=1, reason="暂不采用",
    )

    assert changed["status"] == ("ignored" if action == "ignore" else "expired")
    assert governance.list_records("u1") == []
    assert governance.list_records("u1", status="all")[0]["id"] == row["id"]
    assert governance.history("u1", row["id"])["events"][0]["action"] == action


def test_stale_row_version_does_not_mutate_record_or_append_event() -> None:
    db = FakeMemoryDb()
    row = _record(db, "u1")
    governance = MemoryGovernance(db)
    governance.apply_action("u1", row["id"], action="confirm", expected_row_version=1, reason="ok")

    with pytest.raises(MemoryConflictError):
        governance.apply_action("u1", row["id"], action="expire", expected_row_version=1, reason="stale")

    current = governance.get("u1", row["id"])
    assert current["status"] == "active"
    assert current["row_version"] == 2
    assert len(governance.history("u1", row["id"])["events"]) == 1


def test_merge_is_same_owner_same_type_and_audited() -> None:
    db = FakeMemoryDb()
    canonical = _record(db, "u1", normalized_key="semantic:profile.direction")
    duplicate = _record(db, "u1", normalized_key="semantic:profile.target", display_text="目标方向：AI")
    governance = MemoryGovernance(db)

    merged = governance.merge(
        "u1", canonical["id"], duplicate["id"],
        expected_row_version=1, other_row_version=1, reason="合并重复事实",
    )

    assert merged["id"] == canonical["id"]
    assert merged["status"] == "active"
    assert governance.get("u1", duplicate["id"])["status"] == "superseded"
    assert governance.history("u1", canonical["id"])["events"][0]["action"] == "merge"


def test_merge_and_actions_never_cross_owner_or_type() -> None:
    db = FakeMemoryDb()
    owner_row = _record(db, "u1")
    other_owner = _record(db, "u2", normalized_key="semantic:profile.direction")
    event_row = _record(db, "u1", normalized_key="event:offer:1", memory_type="episodic")
    governance = MemoryGovernance(db)

    with pytest.raises(MemoryNotFoundError):
        governance.apply_action("u2", owner_row["id"], action="ignore", expected_row_version=1, reason="x")
    with pytest.raises(MemoryValidationError):
        governance.merge("u1", owner_row["id"], event_row["id"], expected_row_version=1, other_row_version=1, reason="x")
    with pytest.raises(MemoryNotFoundError):
        governance.merge("u1", owner_row["id"], other_owner["id"], expected_row_version=1, other_row_version=1, reason="x")
