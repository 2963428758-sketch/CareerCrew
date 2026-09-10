from __future__ import annotations


def _seed(runtime, owner_id: str = "u_001") -> str:
    store = runtime.conversation_store
    thread_id = f"consult-report-thread-{owner_id}"
    store.ensure_conversation(thread_id, owner_id, "consult", title="会诊")
    turn = store.next_turn(thread_id, owner_id)
    store.add_user_message(turn["id"], thread_id, owner_id, "怎么准备？", "completed")
    answer = store.add_assistant_message(turn["id"], thread_id, owner_id, "", None, None)
    store.set_message_content(
        owner_id, answer["id"], "建议先补证据",
        metadata={"opinions": {"a": "先补证据", "b": "先补证据并控制风险"},
                  "calls": [{"agent": "a", "name": "secret_tool", "args": {"token": "hidden"}}]},
    )
    return answer["id"]


def test_consultation_report_and_plan_api(client, fake_runtime):
    message_id = _seed(fake_runtime)
    created = client.post("/api/workspace/consult-reports", json={"message_id": message_id})
    assert created.status_code == 201, created.text
    report = created.json()
    assert report["status"] == "draft"
    assert "hidden" not in str(report)

    confirmed = client.patch(
        f"/api/workspace/consult-reports/{report['id']}",
        json={"status": "confirmed", "version": 1},
    )
    assert confirmed.status_code == 200, confirmed.text

    plan = client.post(
        f"/api/workspace/consult-reports/{report['id']}/plans",
        json={"title": "执行计划", "steps": [{"title": "补证据"}]},
    )
    assert plan.status_code == 201, plan.text
    assert plan.json()["status"] == "draft"


def test_consultation_report_does_not_cross_users(tenant_api):
    client, runtime, headers, ids = tenant_api
    message_id = _seed(runtime, ids["bob"])
    # The seeded row belongs to Bob and must not be visible to Alice.
    response = client.post(
        "/api/workspace/consult-reports", headers=headers["alice"],
        json={"message_id": message_id},
    )
    assert response.status_code == 404
