"""Feedback API contracts: server-derived ownership, snapshots, and deletion audit."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _assistant(runtime, user_id: str, legacy_thread: str, question="question", answer="answer"):
    store = runtime.conversation_store
    conv = store.ensure_conversation(legacy_thread, user_id, "chat")
    turn = store.next_turn(conv["id"], user_id)
    store.add_user_message(turn["id"], conv["id"], user_id, question, "completed")
    assistant = store.add_assistant_message(turn["id"], conv["id"], user_id, answer, None, None)
    run = store.start_run(conv["id"], turn["id"], assistant["id"], user_id, "chat", "agent", "model")
    store.set_message_run_id(user_id, assistant["id"], run["id"])
    return store.set_message_content(user_id, assistant["id"], answer), conv


@pytest.mark.web
def test_feedback_upsert_and_reload_only_owner(tenant_api):
    client, runtime, headers, ids = tenant_api
    message, conv = _assistant(runtime, ids["alice"], "feedback-upsert")
    put = client.put(f"/api/messages/{message['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "incorrect", "comment": "first",
    })
    assert put.status_code == 200
    db = runtime.conversation_store._db
    feedback = db._feedback[(ids["alice"], message["id"])]
    assert feedback["id"] not in db._snapshots  # unshared Dislike is metadata/comment only
    changed = client.put(f"/api/messages/{message['id']}/feedback", headers=headers["alice"], json={
        "rating": "positive", "comment": "second",
    })
    assert changed.status_code == 200
    assert feedback["id"] not in db._snapshots  # Like never creates a snapshot
    rows = client.get(f"/api/threads/{conv['id']}/feedback", headers=headers["alice"])
    assert rows.status_code == 200
    assert len(rows.json()) == 1
    assert rows.json()[0]["rating"] == "positive"
    assert rows.json()[0]["reason"] is None
    assert client.put(f"/api/messages/{message['id']}/feedback", headers=headers["bob"], json={
        "rating": "positive",
    }).status_code == 404
    assert client.get(f"/api/threads/{conv['id']}/feedback", headers=headers["bob"]).status_code == 404
    assert client.delete(f"/api/messages/{message['id']}/feedback", headers=headers["bob"]).status_code == 404


@pytest.mark.web
def test_feedback_rejects_ineligible_messages_and_invalid_combinations(tenant_api):
    client, runtime, headers, ids = tenant_api
    store = runtime.conversation_store
    conv = store.ensure_conversation("feedback-invalid", ids["alice"], "chat")
    turn = store.next_turn(conv["id"], ids["alice"])
    user = store.add_user_message(turn["id"], conv["id"], ids["alice"], "q", "completed")
    streaming = store.add_assistant_message(turn["id"], conv["id"], ids["alice"], "a", None, None)
    for message_id in (user["id"], streaming["id"]):
        response = client.put(f"/api/messages/{message_id}/feedback", headers=headers["alice"], json={"rating": "positive"})
        assert response.status_code == 404
    assert client.put(f"/api/messages/{streaming['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative",
    }).status_code == 422
    assert client.put(f"/api/messages/{streaming['id']}/feedback", headers=headers["alice"], json={
        "rating": "positive", "reason": "incorrect",
    }).status_code == 422


@pytest.mark.web
@pytest.mark.parametrize("message_id", ["not-a-uuid", "also-not-a-uuid", "00000000-0000-0000-0000-000000000000x"])
def test_feedback_malformed_message_id_is_not_found(tenant_api, message_id):
    client, _runtime, headers, _ids = tenant_api
    assert client.put(f"/api/messages/{message_id}/feedback", headers=headers["alice"], json={
        "rating": "positive",
    }).status_code == 404
    assert client.delete(f"/api/messages/{message_id}/feedback", headers=headers["alice"]).status_code == 404


@pytest.mark.web
def test_snapshot_redaction_bounds_replacement_and_deletion_audit(tenant_api):
    client, runtime, headers, ids = tenant_api
    first, conv = _assistant(runtime, ids["alice"], "feedback-snapshot", "old one", "old answer")
    _assistant(runtime, ids["alice"], "feedback-snapshot", "old two", "old answer two")
    current, _ = _assistant(
        runtime, ids["alice"], "feedback-snapshot",
        "mail a@b.com phone 13800138000 id 11010519491231002X key sk-abcdef1234567890 ",
        "Bearer eyJaaa.bbb.ccc postgres://secret@host/db C:\\Users\\alice\\secret",
    )
    response = client.put(f"/api/messages/{current['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "tool_failure", "share_context": True,
    })
    assert response.status_code == 200
    db = runtime.conversation_store._db
    feedback = db._feedback[(ids["alice"], current["id"])]
    snapshot = db._snapshots[feedback["id"]]
    texts = [row["content"] for row in snapshot["snapshot_json"]["messages"]]
    assert texts[0].startswith("mail [REDACTED]")
    assert "13800138000" not in " ".join(texts)
    assert "11010519491231002X" not in " ".join(texts)
    assert "sk-abcdef1234567890" not in " ".join(texts)
    assert "postgres://secret" not in " ".join(texts)
    assert "C:\\Users\\alice" not in " ".join(texts)
    assert len(texts) == 6  # rated pair + at most two preceding user/assistant turns
    assert sum(len(text) for text in texts) <= 12_000
    assert 89 <= (datetime.fromisoformat(snapshot["expires_at"]) - datetime.now(timezone.utc)).days <= 90
    # Replacing with an unshared negative or a Like revokes the snapshot immediately.
    assert client.put(f"/api/messages/{current['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "incorrect", "share_context": False,
    }).status_code == 200
    assert feedback["id"] not in db._snapshots
    assert client.delete(f"/api/messages/{current['id']}/feedback", headers=headers["alice"]).json()["deleted"] is True
    audit = db._audit[-1]
    rendered = repr(audit)
    assert "tool_failure" not in rendered and "a@b.com" not in rendered and "C:\\Users" not in rendered
    assert audit["action"] == "feedback.deleted"
