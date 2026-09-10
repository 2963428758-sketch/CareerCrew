from __future__ import annotations


def _seed(runtime, user_id: str = "u_001", thread_id: str = "workspace-thread") -> dict:
    store = runtime.conversation_store
    store.ensure_conversation(thread_id, user_id, "chat", title="工作台测试")
    turn = store.next_turn(thread_id, user_id)
    question = store.add_user_message(
        turn["id"], thread_id, user_id, "如何准备 RAG 面试？", "completed"
    )
    answer = store.add_assistant_message(
        turn["id"], thread_id, user_id, "先准备召回、重排和评测案例", None, None
    )
    store.set_message_content(user_id, answer["id"], answer["content"])
    return {"thread": thread_id, "question": question, "answer": answer}


def test_workspace_api_supports_traceability(client, fake_runtime):
    seeded = _seed(fake_runtime)

    search = client.get("/api/workspace/search", params={"q": "RAG 面试"})
    assert search.status_code == 200, search.text
    assert search.json()["items"][0]["message_id"] == seeded["question"]["id"]

    bookmark = client.put(
        f"/api/workspace/messages/{seeded['answer']['id']}/bookmark",
        json={"note": "重点", "tags": ["RAG"]},
    )
    assert bookmark.status_code == 200, bookmark.text

    action = client.post(
        "/api/workspace/action-items",
        json={"message_id": seeded["answer"]["id"], "title": "补案例", "note": "写指标"},
    )
    assert action.status_code == 201, action.text
    assert action.json()["source_message_id"] == seeded["answer"]["id"]

    branch = client.post(
        "/api/workspace/branches",
        json={"source_thread_id": seeded["thread"], "cutoff_message_id": seeded["question"]["id"]},
    )
    assert branch.status_code == 201, branch.text
    assert branch.json()["message_count"] == 1


def test_workspace_api_hides_foreign_message(tenant_api):
    client, runtime, headers, ids = tenant_api
    seeded = _seed(runtime, ids["alice"], "alice-workspace")

    response = client.put(
        f"/api/workspace/messages/{seeded['answer']['id']}/bookmark",
        headers=headers["bob"],
        json={"note": "不应看到"},
    )
    assert response.status_code == 404
    assert client.get("/api/workspace/search", headers=headers["bob"], params={"q": "RAG"}).json()["items"] == []
