from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from careercrew_core.conversation.db import FakeConversationDb


def _feedback_fields(message_id: str) -> dict:
    return {
        "id": str(uuid4()), "thread_id": str(uuid4()), "turn_id": str(uuid4()),
        "message_id": message_id, "run_id": str(uuid4()), "rating": "negative",
        "reason": "incorrect", "comment": None, "share_context": True,
    }


def _snapshot_fields() -> dict:
    return {
        "id": str(uuid4()), "snapshot_json": {"messages": []},
        "redaction_version": "feedback_snapshot.v1", "redaction_count": 0,
        "expires_at": "2026-01-01T00:00:00+00:00",
    }


def test_fake_feedback_snapshot_failure_leaves_existing_effective_consent_unchanged():
    db = FakeConversationDb()
    message_id = str(uuid4())
    feedback = db.replace_feedback_with_snapshot("u1", _feedback_fields(message_id), _snapshot_fields())
    before_feedback, before_snapshots = deepcopy(db._feedback), deepcopy(db._snapshots)
    malformed_snapshot = _snapshot_fields()
    del malformed_snapshot["expires_at"]

    with pytest.raises(KeyError):
        db.replace_feedback_with_snapshot("u1", _feedback_fields(message_id), malformed_snapshot)

    assert db._feedback == before_feedback
    assert db._snapshots == before_snapshots
    assert db._feedback[("u1", message_id)]["share_context"] is True
    assert feedback["id"] in db._snapshots


def test_fake_feedback_revoke_removes_snapshot_with_the_same_atomic_write():
    db = FakeConversationDb()
    message_id = str(uuid4())
    feedback = db.replace_feedback_with_snapshot("u1", _feedback_fields(message_id), _snapshot_fields())
    revoked = _feedback_fields(message_id)
    revoked.update(rating="negative", share_context=False)

    # Persistence itself enforces effective consent, independent of its caller.
    result = db.replace_feedback_with_snapshot("u1", revoked, _snapshot_fields())

    assert result["share_context"] is False
    assert feedback["id"] == result["id"]
    assert result["id"] not in db._snapshots


def test_fake_feedback_delete_audit_failure_rolls_back_feedback_and_snapshot():
    db = FakeConversationDb()
    message_id = str(uuid4())
    feedback = db.replace_feedback_with_snapshot("u1", _feedback_fields(message_id), _snapshot_fields())
    before_feedback, before_snapshots, before_audit = (
        deepcopy(db._feedback), deepcopy(db._snapshots), deepcopy(db._audit),
    )

    with pytest.raises(TypeError):
        db.delete_feedback_with_audit("u1", message_id, {"deleted": object()})

    assert db._feedback == before_feedback
    assert db._snapshots == before_snapshots
    assert db._audit == before_audit
    assert feedback["id"] in db._snapshots
