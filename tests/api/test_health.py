"""Phase 0: 骨架验证 —— health / config 端点。"""
from __future__ import annotations

import pytest


@pytest.mark.web
def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["ready"] is True  # FakeRuntime 已 initialized
    assert data["model"] == "fake-model"


@pytest.mark.web
def test_config(client, valid_settings, monkeypatch):
    """config 端点返回 settings 汇总（monkeypatch load_settings，不依赖仓库真实配置/环境变量）。"""
    from careercrew_core.state import settings as settings_module

    monkeypatch.setattr(settings_module, "load_settings", lambda *a, **k: valid_settings)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["llm"] == valid_settings.llm.model
    assert data["vector_store"] == valid_settings.vector_store.backend
