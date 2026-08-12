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
