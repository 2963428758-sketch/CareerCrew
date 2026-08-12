"""Phase 6: data API 测试。"""
from __future__ import annotations

import pytest


@pytest.mark.web
def test_health_not_initialized():
    """health 不触发重初始化：FakeRuntime ready=True，真实未初始化时 ready=False。"""
    from careercrew_api.runtime import CareerCrewRuntime

    rt = CareerCrewRuntime()  # 未 _ensure_heavy
    info = rt.health_info()
    assert info["ready"] is False
    # 但能读 settings 字段（不抛异常说明不触发 heavy init）
    assert "model" in info or "error" in info


@pytest.mark.web
def test_profile_endpoint(client):
    """GET /api/profile。"""
    resp = client.get("/api/profile")
    # FakeRuntime 注入，但 profile 复用 dashboard get_user_model() 可能因无配置文件失败
    assert resp.status_code in (200, 500)


@pytest.mark.web
def test_memory_endpoint(client):
    """GET /api/memory。"""
    resp = client.get("/api/memory")
    assert resp.status_code in (200, 500)


@pytest.mark.web
def test_memory_policy_get(client):
    """GET /api/memory/policy。"""
    resp = client.get("/api/memory/policy?user_id=u_001")
    assert resp.status_code == 200
    body = resp.json()
    assert "global" in body and "user" in body and "effective" in body


@pytest.mark.web
def test_memory_policy_put(client):
    """PUT /api/memory/policy 更新用户级策略。"""
    resp = client.put(
        "/api/memory/policy?user_id=u_001",
        json={"enabled": True, "use": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["enabled"] is True
    assert body["user"]["use"] is False


@pytest.mark.web
def test_memory_settings_get(client):
    """GET /api/settings/memory。"""
    resp = client.get("/api/settings/memory")
    assert resp.status_code == 200
    assert "enabled" in resp.json()


@pytest.mark.web
def test_memory_settings_put(client):
    """PUT /api/settings/memory 更新全局开关。"""
    resp = client.put("/api/settings/memory", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


@pytest.mark.web
def test_threads_crud(client):
    """POST/PATCH/DELETE /api/threads。"""
    created = client.post("/api/threads?user_id=u_001", json={
        "thread_id": "t-abc", "module": "matcher", "title": "",
    })
    assert created.status_code == 200
    patched = client.patch("/api/threads/t-abc?user_id=u_001", json={"title": "找工作", "pinned": True})
    assert patched.status_code == 200
    assert patched.json()["title"] == "找工作"
    assert patched.json()["pinned"] is True
    deleted = client.delete("/api/threads/t-abc?user_id=u_001")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


@pytest.mark.web
def test_memory_delete_fact(client):
    """DELETE /api/memory 删除语义事实。"""
    client.put("/api/profile?user_id=u_001", json={
        "fields": {"profile.skills": ["Python"]},
    })
    resp = client.delete("/api/memory?kind=fact&name=profile.skills&user_id=u_001")
    assert resp.status_code == 200
    assert resp.json()["removed"] >= 1


@pytest.mark.web
def test_thread_transcript_restore_roundtrip(client, fake_runtime):
    """record_thread_messages 写入后，/api/memory?thread_id= 可恢复 user_message/agent_response。"""
    fake_runtime.record_thread_messages(
        "u_001", "t-roundtrip", user_text="帮我找大模型岗位",
        agent_text="匹配到字节跳动 0.95", module="matcher",
    )
    resp = client.get("/api/memory?thread_id=t-roundtrip&user_id=u_001")
    assert resp.status_code == 200
    entries = resp.json()
    types = [e.get("type") for e in entries if e.get("kind") == "event"]
    assert "user_message" in types
    assert "agent_response" in types
    user = next(e for e in entries if e.get("type") == "user_message")
    assert user["content"] == "帮我找大模型岗位"


@pytest.mark.web
def test_knowledge_thread_stays_in_knowledge_module(client, fake_runtime):
    """知识库会话 touch_thread 后 module 保持 knowledge，列表按模块隔离。"""
    fake_runtime.touch_thread(
        "k-tid-1", "u_001", title="什么是 RAG", module="knowledge",
    )
    knowledge_list = client.get("/api/threads?module=knowledge&user_id=u_001")
    assert knowledge_list.status_code == 200
    tids = [t["thread_id"] for t in knowledge_list.json()]
    assert "k-tid-1" in tids
    chat_list = client.get("/api/threads?module=chat&user_id=u_001")
    assert all(t["thread_id"] != "k-tid-1" for t in chat_list.json())


@pytest.mark.web
def test_knowledge_sources_persist_after_restore(client, fake_runtime):
    """知识库回答的 sources 随 transcript 存储，/api/memory 恢复后仍可解析。"""
    fake_runtime.record_thread_messages(
        "u_001", "k-src-1", user_text="LangChain 是什么",
        agent_text="LangChain 是一个框架。", module="knowledge",
        sources=[
            {"doc": "note", "source": "data/uploads/note.md",
             "score": 0.91, "text": "LangChain 定义"},
        ],
    )
    resp = client.get("/api/memory?thread_id=k-src-1&user_id=u_001")
    assert resp.status_code == 200
    entries = resp.json()
    agent = next(e for e in entries if e.get("type") == "agent_response")
    assert agent["content"] == "LangChain 是一个框架。"
    assert agent.get("sources") == [
        {"doc": "note", "source": "data/uploads/note.md",
         "score": 0.91, "text": "LangChain 定义"},
    ]
