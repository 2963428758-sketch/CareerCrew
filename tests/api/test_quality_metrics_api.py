"""Quality dashboard metrics API: aggregates, coverage sample sizes, and T5.5 alert."""
from __future__ import annotations

import pytest


def _assistant(runtime, user_id: str, legacy_thread: str, question: str, answer: str,
               agent: str = "agent", prompt_version: str = "v1", agent_version: str = "ag-v1"):
    store = runtime.conversation_store
    conversation = store.ensure_conversation(legacy_thread, user_id, "chat")
    turn = store.next_turn(conversation["id"], user_id)
    store.add_user_message(turn["id"], conversation["id"], user_id, question, "completed")
    assistant = store.add_assistant_message(turn["id"], conversation["id"], user_id, answer, None, None)
    run = store.start_run(conversation["id"], turn["id"], assistant["id"], user_id,
                          "chat", agent, "model", prompt_version=prompt_version,
                          agent_version=agent_version)
    store.set_message_run_id(user_id, assistant["id"], run["id"])
    store.finish_run(user_id, run["id"], "completed", latency_ms=1000, input_tokens=10, output_tokens=20)
    return store.set_message_content(user_id, assistant["id"], answer)


@pytest.mark.web
def test_metrics_aggregates_with_coverage_and_version_trend(tenant_api):
    client, runtime, headers, ids = tenant_api
    alice = ids["alice"]
    good = _assistant(runtime, alice, "metrics-good", "q1", "a1")
    bad = _assistant(runtime, alice, "metrics-bad", "q2", "a2", prompt_version="v1")
    unrated = _assistant(runtime, alice, "metrics-unrated", "q3", "a3")
    assert client.put(f"/api/messages/{good['id']}/feedback", headers=headers["alice"], json={
        "rating": "positive",
    }).status_code == 200
    assert client.put(f"/api/messages/{bad['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "tool_failure",
    }).status_code == 200

    payload = client.get("/api/quality/metrics", headers=headers["quality_reviewer"]).json()
    assert payload["runs"] == 3
    assert payload["positive_count"] == 1 and payload["negative_count"] == 1
    assert payload["helpful_rate"] == 0.5
    assert payload["feedback_coverage"] == pytest.approx(2 / 3, abs=0.001)
    assert payload["negative_reason_distribution"] == {"tool_failure": 1}
    assert payload["tool_failure_share"] == 1.0
    assert payload["rag_failure_share"] == 0.0
    assert payload["median_latency_ms"] == 1000
    assert payload["p95_latency_ms"] == 1000
    assert payload["avg_input_tokens"] == 10
    assert payload["avg_output_tokens"] == 20
    assert payload["unversioned_run_count"] == 0 and payload["unversioned_run_rate"] == 0.0
    trend = {row["prompt_version"]: row for row in payload["helpful_rate_by_prompt_version"]}
    assert trend["v1"]["feedback_count"] == 2 and trend["v1"]["rate"] == 0.5


@pytest.mark.web
def test_metrics_filters_scope_and_unversioned_alert_zero_when_all_versioned(tenant_api):
    client, runtime, headers, ids = tenant_api
    alice = ids["alice"]
    v1 = _assistant(runtime, alice, "metrics-f1", "q1", "a1", prompt_version="v1")
    v2 = _assistant(runtime, alice, "metrics-f2", "q2", "a2", prompt_version="v2")
    assert client.put(f"/api/messages/{v1['id']}/feedback", headers=headers["alice"], json={
        "rating": "negative", "reason": "incorrect",
    }).status_code == 200
    assert client.put(f"/api/messages/{v2['id']}/feedback", headers=headers["alice"], json={
        "rating": "positive",
    }).status_code == 200

    scoped = client.get("/api/quality/metrics", params={"prompt_version": "v1"},
                        headers=headers["quality_reviewer"]).json()
    assert scoped["runs"] == 1 and scoped["negative_count"] == 1
    assert scoped["unversioned_run_count"] == 0 and scoped["unversioned_run_rate"] == 0.0

    unversioned = _assistant(runtime, alice, "metrics-unversioned", "q3", "a3",
                             prompt_version="unversioned", agent_version="unversioned")
    assert client.put(f"/api/messages/{unversioned['id']}/feedback", headers=headers["alice"], json={
        "rating": "positive",
    }).status_code == 200
    alerts = client.get("/api/quality/metrics", headers=headers["quality_reviewer"]).json()
    assert alerts["unversioned_run_count"] == 1 and alerts["unversioned_run_rate"] == pytest.approx(1 / 3, abs=0.001)

    assert client.get("/api/quality/metrics", headers=headers["alice"]).status_code == 403