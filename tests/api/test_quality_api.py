"""Quality reviewer API: narrow metadata, redacted snapshots, and diagnostics only."""
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
    return store.set_message_content(user_id, assistant["id"], answer), run


@pytest.mark.web
def test_quality_reviewer_reads_negative_metadata_and_only_authorized_snapshot(tenant_api):
    client, runtime, headers, ids = tenant_api
    unshared, _ = _assistant(runtime, ids["alice"], "quality-unshared", "private question", "private answer")
    shared, _ = _assistant(runtime, ids["alice"], "quality-shared", "mail a@b.com", "Bearer eyJaaa.bbb.ccc")
    positive, _ = _assistant(runtime, ids["alice"], "quality-positive", "ordinary question", "ordinary answer")

    assert client.put(f"/api/messages/{unshared['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "incorrect", "comment": "keep private", "share_context": False,
    }).status_code == 200
    assert client.put(f"/api/messages/{shared['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "tool_failure", "share_context": True,
    }).status_code == 200
    assert client.put(f"/api/messages/{positive['id']}/feedback", headers=headers["alice"], json={
        "rating": "positive",
    }).status_code == 200

    rows = client.get("/api/quality/bad-cases", headers=headers["quality_reviewer"])
    assert rows.status_code == 200
    payload = rows.json()
    assert len(payload) == 2
    assert {row["reason"] for row in payload} == {"incorrect", "tool_failure"}
    assert all("comment" not in row and "thread_id" not in row and "message_id" not in row for row in payload)
    by_reason = {row["reason"]: row for row in payload}
    assert by_reason["incorrect"]["snapshot_available"] is False
    assert by_reason["tool_failure"]["snapshot_available"] is True

    unshared_detail = client.get(
        f"/api/quality/bad-cases/{by_reason['incorrect']['feedback_id']}", headers=headers["quality_reviewer"],
    )
    assert unshared_detail.status_code == 200
    assert unshared_detail.json()["snapshot_available"] is False
    assert client.get(
        f"/api/quality/bad-cases/{by_reason['incorrect']['feedback_id']}/snapshot",
        headers=headers["quality_reviewer"],
    ).status_code == 404

    snapshot = client.get(
        f"/api/quality/bad-cases/{by_reason['tool_failure']['feedback_id']}/snapshot",
        headers=headers["quality_reviewer"],
    )
    assert snapshot.status_code == 200
    rendered = repr(snapshot.json())
    assert "a@b.com" not in rendered and "eyJaaa.bbb.ccc" not in rendered
    audit = runtime.conversation_store._db._audit[-1]
    assert audit["action"] == "quality.snapshot.viewed"
    assert "a@b.com" not in repr(audit) and "eyJaaa.bbb.ccc" not in repr(audit)


@pytest.mark.web
def test_quality_reviewer_diagnostics_are_limited_to_negative_feedback_runs(tenant_api):
    client, runtime, headers, ids = tenant_api
    negative, run = _assistant(runtime, ids["alice"], "quality-diagnostics", "q", "a")
    runtime.conversation_store.add_retrieval(ids["alice"], run["id"], 0, query_text_redacted="private q", document_id="doc-1")
    runtime.conversation_store.add_tool_call(
        ids["alice"], run["id"], "memory_search", input_redacted={"query": "[REDACTED]"}, output_summary="private output",
    )
    assert client.put(f"/api/messages/{negative['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "tool_failure",
    }).status_code == 200
    feedback_id = client.get("/api/quality/bad-cases", headers=headers["quality_reviewer"]).json()[0]["feedback_id"]

    diagnostic = client.get(f"/api/quality/bad-cases/{feedback_id}/diagnostics", headers=headers["quality_reviewer"])
    assert diagnostic.status_code == 200
    rendered = repr(diagnostic.json())
    assert "private q" not in rendered and "private output" not in rendered
    assert diagnostic.json()["retrievals"] == [{"document_id": "doc-1", "chunk_id": None, "recall_score": None,
                                                   "rerank_score": None, "rank_before": None, "rank_after": None,
                                                   "used_in_final_context": False, "retrieval_source": "auto"}]
    assert diagnostic.json()["tool_calls"][0]["tool_name"] == "memory_search"


@pytest.mark.web
def test_quality_rbac_rejects_nonreviewers_and_regular_conversation_access(tenant_api):
    client, runtime, headers, ids = tenant_api
    message, conversation_run = _assistant(runtime, ids["alice"], "quality-rbac", "secret question", "secret answer")
    assert client.put(f"/api/messages/{message['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "incorrect", "share_context": True,
    }).status_code == 200

    assert client.get("/api/quality/bad-cases", headers=headers["alice"]).status_code == 403
    assert client.get("/api/quality/bad-cases", headers=headers["bob"]).status_code == 403
    reviewer = headers["quality_reviewer"]
    assert client.get(f"/api/threads/{conversation_run['thread_id']}/messages", headers=reviewer).status_code == 403
    assert client.get(f"/api/threads/{conversation_run['thread_id']}/feedback", headers=reviewer).status_code == 403
    assert client.get("/api/auth/users", headers=reviewer).status_code == 403
