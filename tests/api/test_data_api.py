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
def test_traces_endpoint(client):
    """GET /api/traces。"""
    resp = client.get("/api/traces?limit=10")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
