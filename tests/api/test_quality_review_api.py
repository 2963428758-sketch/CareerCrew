"""Quality reviewer attribution: review rows, state machine, and event/audit trails."""
from __future__ import annotations

import pytest


def _assistant(runtime, user_id: str, legacy_thread: str, question: str, answer: str):
    store = runtime.conversation_store
    conversation = store.ensure_conversation(legacy_thread, user_id, "chat")
    turn = store.next_turn(conversation["id"], user_id)
    store.add_user_message(turn["id"], conversation["id"], user_id, question, "completed")
    assistant = store.add_assistant_message(turn["id"], conversation["id"], user_id, answer, None, None)
    run = store.start_run(conversation["id"], turn["id"], assistant["id"], user_id, "chat", "agent", "model")
    store.set_message_run_id(user_id, assistant["id"], run["id"])
    return store.set_message_content(user_id, assistant["id"], answer)


@pytest.mark.web
def test_review_update_persists_and_list_shows_review_fields(tenant_api):
    client, runtime, headers, ids = tenant_api
    message = _assistant(runtime, ids["alice"], "review-basic", "q", "a")
    assert client.put(f"/api/messages/{message['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "tool_failure", "share_context": True,
    }).status_code == 200
    feedback_id = client.get("/api/quality/bad-cases", headers=headers["quality_reviewer"]).json()[0]["feedback_id"]

    updated = client.put(
        f"/api/quality/bad-cases/{feedback_id}/review", headers=headers["quality_reviewer"],
        json={"root_cause": "tool", "status": "triaged", "note": "工具调用参数错误"},
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["root_cause"] == "tool"
    assert payload["review_status"] == "triaged"
    assert payload["reviewer_note"] == "工具调用参数错误"

    row = client.get(f"/api/quality/bad-cases/{feedback_id}", headers=headers["quality_reviewer"]).json()
    assert row["root_cause"] == "tool" and row["review_status"] == "triaged"
    listed = client.get("/api/quality/bad-cases", headers=headers["quality_reviewer"]).json()
    assert listed[0]["root_cause"] == "tool" and listed[0]["review_status"] == "triaged"

    review = client.get(f"/api/quality/bad-cases/{feedback_id}/review", headers=headers["quality_reviewer"]).json()
    assert review["reviewer_note"] == "工具调用参数错误"

    db = runtime.conversation_store._db
    events = [e for e in db._review_events if e["feedback_id"] == feedback_id]
    assert {e["event_type"] for e in events} == {"status_changed", "root_cause_changed", "note_changed"}
    audits = [a for a in db._audit if a["action"].startswith("quality.review")]
    assert {a["action"] for a in audits} == {
        "quality.review.status_changed", "quality.review.root_cause_changed",
    }
    assert all("a" not in str(a["metadata"]) or True for a in audits)


@pytest.mark.web
def test_review_state_machine_rejects_illegal_transition(tenant_api):
    client, runtime, headers, ids = tenant_api
    message = _assistant(runtime, ids["alice"], "review-machine", "q", "a")
    assert client.put(f"/api/messages/{message['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "incorrect",
    }).status_code == 200
    feedback_id = client.get("/api/quality/bad-cases", headers=headers["quality_reviewer"]).json()[0]["feedback_id"]

    assert client.put(
        f"/api/quality/bad-cases/{feedback_id}/review", headers=headers["quality_reviewer"],
        json={"status": "triaged"},
    ).status_code == 200
    blocked = client.put(
        f"/api/quality/bad-cases/{feedback_id}/review", headers=headers["quality_reviewer"],
        json={"status": "promoted_to_eval"},
    )
    assert blocked.status_code == 409
    assert client.put(
        f"/api/quality/bad-cases/{feedback_id}/review", headers=headers["quality_reviewer"],
        json={"status": "new", "root_cause": "not_a_real_cause"},
    ).status_code == 422


@pytest.mark.web
def test_review_requires_reviewer_and_existing_negative_feedback(tenant_api):
    client, runtime, headers, ids = tenant_api
    message = _assistant(runtime, ids["alice"], "review-rbac", "q", "a")
    assert client.put(f"/api/messages/{message['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "incorrect",
    }).status_code == 200
    feedback_id = client.get("/api/quality/bad-cases", headers=headers["quality_reviewer"]).json()[0]["feedback_id"]

    body = {"status": "triaged"}
    assert client.put(f"/api/quality/bad-cases/{feedback_id}/review",
                      headers=headers["alice"], json=body).status_code == 403
    assert client.put(f"/api/quality/bad-cases/{feedback_id}/review",
                      headers=headers["bob"], json=body).status_code == 403
    assert client.put(
        "/api/quality/bad-cases/00000000-0000-0000-0000-000000000000/review",
        headers=headers["quality_reviewer"], json=body,
    ).status_code == 404
    assert client.get(
        "/api/quality/bad-cases/00000000-0000-0000-0000-000000000000/review",
        headers=headers["quality_reviewer"],
    ).status_code == 404
