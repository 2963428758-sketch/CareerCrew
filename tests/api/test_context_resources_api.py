"""T3.4 context resources API + mention 越权拒绝（§15 / §34）。

- GET /api/context/resources：本人 private + public 知识 + 本人简历；他人 private 不可见；q/types 过滤。
- knowledge.ask / match 等发送带越权 mention → 422（服务端二次校验）。
"""
from __future__ import annotations

import json

import pytest


@pytest.mark.web
def test_context_resources_lists_own_private_and_public(client, fake_runtime):
    fake_runtime.knowledge_docs_by_user["u_001"] = [
        {"doc": "mine", "source": "mine.md", "points": 2,
         "owner_user_id": "u_001", "visibility": "private"},
        {"doc": "shared", "source": "shared.md", "points": 3,
         "owner_user_id": "u_001", "visibility": "public"},
        {"doc": "other-private", "source": "o.md", "points": 1,
         "owner_user_id": "u_999", "visibility": "private"},
    ]
    fake_runtime.resume_library_items["u_001"] = [("res-1", "李雷的简历.pdf")]

    resp = client.get("/api/context/resources")
    assert resp.status_code == 200
    items = resp.json()["items"]

    ids = {(i["type"], i["id"]) for i in items}
    assert ("knowledge_document", "mine") in ids
    assert ("knowledge_document", "shared") in ids
    assert ("knowledge_document", "other-private") not in ids  # 他人 private 不可见
    assert ("resume", "res-1") in ids


@pytest.mark.web
def test_context_resources_type_and_query_filter(client, fake_runtime):
    fake_runtime.knowledge_docs_by_user["u_001"] = [
        {"doc": "rag-notes", "source": "a.md", "points": 1,
         "owner_user_id": "u_001", "visibility": "private"},
        {"doc": "interview-qa", "source": "b.md", "points": 1,
         "owner_user_id": "u_001", "visibility": "private"},
    ]
    fake_runtime.resume_library_items["u_001"] = [("res-1", "李雷的简历.pdf")]

    # types=knowledge 只返回知识文档
    resp = client.get("/api/context/resources", params={"types": "knowledge"})
    assert {i["type"] for i in resp.json()["items"]} == {"knowledge_document"}

    # q 过滤名称
    resp = client.get("/api/context/resources", params={"types": "knowledge", "q": "rag"})
    assert {i["id"] for i in resp.json()["items"]} == {"rag-notes"}

    # types=resume 只返回简历
    resp = client.get("/api/context/resources", params={"types": "resume"})
    assert {i["type"] for i in resp.json()["items"]} == {"resume"}


@pytest.mark.web
def test_context_resources_invalid_type_422(client):
    resp = client.get("/api/context/resources", params={"types": "bogus"})
    assert resp.status_code == 422


@pytest.mark.web
def test_knowledge_ask_rejects_other_users_private_mention(tenant_api):
    client, runtime, headers, ids = tenant_api
    runtime.knowledge_docs_by_user[ids["alice"]] = [
        {"doc": "alice-private", "source": "a.md", "points": 2,
         "owner_user_id": ids["alice"], "visibility": "private"},
    ]
    runtime.knowledge_docs_by_user[ids["bob"]] = [
        {"doc": "bob-private", "source": "b.md", "points": 1,
         "owner_user_id": ids["bob"], "visibility": "private"},
    ]

    # B 引用 A 的 private 文档 → 422
    resp = client.post("/api/knowledge/ask", json={
        "question": "A 的私有内容", "thread_id": "k-mention",
        "mentions": [{"type": "knowledge_document", "id": "alice-private"}],
    }, headers=headers["bob"])
    assert resp.status_code == 422


@pytest.mark.web
def test_knowledge_ask_accepts_own_mention_and_records_metadata(tenant_api):
    client, runtime, headers, ids = tenant_api
    runtime.knowledge_docs_by_user[ids["bob"]] = [
        {"doc": "bob-private", "source": "b.md", "points": 1,
         "owner_user_id": ids["bob"], "visibility": "private"},
    ]
    runtime.knowledge_output_by_user[ids["bob"]] = "基于 bob 私有文档的回答"

    resp = client.post("/api/knowledge/ask", json={
        "question": "我的文档内容", "thread_id": "k-mention-ok",
        "mentions": [{"type": "knowledge_document", "id": "bob-private"}],
    }, headers=headers["bob"])
    assert resp.status_code == 200
    events = [json.loads(line) for line in resp.text.splitlines() if line]
    assert events[-1]["content"] == "基于 bob 私有文档的回答"

    # user message metadata 记录 mentions
    msgs = runtime.conversation_store.list_messages(events[-1]["thread_id"], ids["bob"])
    user_msg = next(m for m in msgs if m["role"] == "user")
    assert user_msg["metadata"]["mentions"][0]["id"] == "bob-private"


@pytest.mark.web
def test_match_rejects_forged_public_mention(tenant_api):
    client, runtime, headers, ids = tenant_api
    runtime.knowledge_docs_by_user[ids["alice"]] = [
        {"doc": "alice-private", "source": "a.md", "points": 2,
         "owner_user_id": ids["alice"], "visibility": "private"},
    ]

    # B 伪造引用 A 的 private 文档（不可能在 resources 列表里出现）→ 422
    resp = client.post("/api/chat/match", json={
        "intent": "找岗位", "thread_id": "m-mention",
        "mentions": [{"type": "knowledge_document", "id": "alice-private"}],
    }, headers=headers["bob"])
    assert resp.status_code == 422
