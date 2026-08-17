"""Phase 6 eval-case lifecycle API: promote → edit → approve → export (§29/§30/§34)."""
from __future__ import annotations

import json

import pytest


def _negative_with_context(runtime, user_id: str, legacy_thread: str,
                           question: str = "q", answer: str = "a",
                           prompt_version: str = "v1"):
    store = runtime.conversation_store
    conversation = store.ensure_conversation(legacy_thread, user_id, "chat")
    turn = store.next_turn(conversation["id"], user_id)
    store.add_user_message(turn["id"], conversation["id"], user_id, question, "completed")
    assistant = store.add_assistant_message(turn["id"], conversation["id"], user_id, answer, None, None)
    run = store.start_run(conversation["id"], turn["id"], assistant["id"], user_id,
                          "chat", "career-agent", "model-x", prompt_version=prompt_version,
                          agent_version="ag-v1")
    store.set_message_run_id(user_id, assistant["id"], run["id"])
    store.finish_run(user_id, run["id"], "completed", latency_ms=100, input_tokens=5, output_tokens=9)
    message = store.set_message_content(user_id, assistant["id"], answer)
    store.put_feedback(user_id, message["id"], rating="negative", reason="tool_failure",
                       share_context=True, comment=None)
    return message


@pytest.mark.web
def test_promote_edit_approve_export_lifecycle(tenant_api):
    client, runtime, headers, ids = tenant_api
    alice = ids["alice"]
    message = _negative_with_context(runtime, alice, "eval-lifecycle")
    feedback = runtime.conversation_store.list_quality_feedback()[0]
    feedback_id = feedback["feedback_id"]

    promoted = client.post(f"/api/quality/bad-cases/{feedback_id}/promote",
                           headers=headers["quality_reviewer"])
    assert promoted.status_code == 200, promoted.text
    case = promoted.json()
    assert case["status"] == "draft"
    assert case["target_agent"] == "career-agent"
    assert case["input_text"] == "q"
    assert case["source_prompt_version"] == "v1"
    assert case["failure_reason"] == "tool_failure"
    assert (case["context"] or {}).get("messages")

    review = client.get(f"/api/quality/bad-cases/{feedback_id}/review",
                        headers=headers["quality_reviewer"]).json()
    assert review["review_status"] == "promoted_to_eval"
    assert client.post(f"/api/quality/bad-cases/{feedback_id}/promote",
                       headers=headers["quality_reviewer"]).status_code == 409

    case_id = case["id"]
    edited = client.put(f"/api/quality/eval-cases/{case_id}", headers=headers["quality_reviewer"], json={
        "expected_behavior": "must offer a fallback when the tool fails",
        "rubric": {"must_include": ["fallback"]},
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["expected_behavior"] == "must offer a fallback when the tool fails"

    assert client.post(f"/api/quality/eval-cases/{case_id}/approve",
                       headers=headers["quality_reviewer"]).status_code == 200
    approved = client.get(f"/api/quality/eval-cases/{case_id}", headers=headers["quality_reviewer"]).json()
    assert approved["status"] == "approved" and approved["approved_by"] == ids["quality_reviewer"]

    export = client.get("/api/quality/eval-cases/export", headers=headers["quality_reviewer"])
    assert export.status_code == 200
    rows = [json.loads(line) for line in export.json().strip().splitlines()]
    assert len(rows) == 1 and rows[0]["id"] == case_id
    assert rows[0]["agent"] == "career-agent" and rows[0]["rubric"] == {"must_include": ["fallback"]}
    assert rows[0]["source"]["feedback_id"] == feedback_id

    audits = runtime.conversation_store._db._audit
    actions = [a["action"] for a in audits]
    assert "quality.eval_draft_created" in actions
    assert "quality.eval_case.approved" in actions


@pytest.mark.web
def test_promote_guardrails_and_approval_requirements(tenant_api):
    client, runtime, headers, ids = tenant_api
    alice = ids["alice"]

    no_context = _negative_with_context(runtime, alice, "eval-noctx")
    feedback = runtime.conversation_store.list_quality_feedback()[0]
    feedback_id = feedback["feedback_id"]
    store = runtime.conversation_store
    store.put_feedback(alice, no_context["id"], rating="negative", reason="tool_failure",
                       share_context=False, comment=None)
    resp = client.post(f"/api/quality/bad-cases/{feedback_id}/promote",
                       headers=headers["quality_reviewer"])
    assert resp.status_code == 409 and "shared-context" in resp.json()["detail"]

    store.put_feedback(alice, no_context["id"], rating="negative", reason="tool_failure",
                       share_context=True, comment=None)
    case = client.post(f"/api/quality/bad-cases/{feedback_id}/promote",
                       headers=headers["quality_reviewer"]).json()
    case_id = case["id"]
    assert client.post(f"/api/quality/eval-cases/{case_id}/approve",
                       headers=headers["quality_reviewer"]).status_code == 409

    bad_rubric = client.put(f"/api/quality/eval-cases/{case_id}", headers=headers["quality_reviewer"],
                            json={"rubric": "not-an-object"})
    assert bad_rubric.status_code == 422
    assert client.put(f"/api/quality/eval-cases/{case_id}", headers=headers["quality_reviewer"], json={
        "expected_behavior": "behave", "rubric": {"must_include": ["x"]},
    }).status_code == 200
    approved = client.post(f"/api/quality/eval-cases/{case_id}/approve",
                           headers=headers["quality_reviewer"])
    assert approved.status_code == 200

    deprecated = client.put(f"/api/quality/eval-cases/{case_id}", headers=headers["quality_reviewer"],
                            json={"status": "deprecated"})
    assert deprecated.status_code == 200 and deprecated.json()["status"] == "deprecated"
    assert client.get("/api/quality/eval-cases/export", headers=headers["quality_reviewer"]).json().strip() == ""
    assert client.get("/api/quality/eval-cases", params={"status": "bogus"},
                      headers=headers["quality_reviewer"]).status_code == 422
    assert client.get("/api/quality/eval-cases", headers=headers["alice"]).status_code == 403
    assert client.get("/api/quality/eval-cases/export", headers=headers["alice"]).status_code == 403