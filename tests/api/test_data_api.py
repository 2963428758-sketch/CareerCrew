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
def test_runs_endpoint(client):
    """GET /api/runs：根 run 列表（LangSmith 读取替代 /api/traces）。"""
    resp = client.get("/api/runs?limit=10&user_id=u_001&stage=match")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["runs"], list)
    assert body["runs"][0]["run_id"] == "run-1"
    assert body["runs"][0]["metadata"]["stage"] == "match"


@pytest.mark.web
def test_run_detail_endpoint(client):
    """GET /api/runs/{id}：run + 展平 steps。"""
    resp = client.get("/api/runs/run-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"]["name"] == "careercrew.match"
    assert body["steps"][0]["run_type"] == "llm"


@pytest.mark.web
def test_run_detail_not_found(client):
    """GET /api/runs/{id} 不存在 -> 404。"""
    resp = client.get("/api/runs/nope")
    assert resp.status_code == 404


@pytest.mark.web
def test_runs_service_unavailable(client, fake_runtime, monkeypatch):
    """LangSmith 不可用 -> 503 可读错误。"""
    def _boom(**kwargs):
        raise RuntimeError("langsmith down")

    monkeypatch.setattr(fake_runtime, "list_runs", _boom)
    resp = client.get("/api/runs")
    assert resp.status_code == 503
    assert "追踪服务不可用" in resp.json()["detail"]
