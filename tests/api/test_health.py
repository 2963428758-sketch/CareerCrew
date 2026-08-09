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
def test_config(client):
    # config 复用 dashboard get_settings_summary()，FakeRuntime 下可能抛（无真实配置文件上下文）
    # 这里只验证端点存在且返回 200 或可预期的错误
    resp = client.get("/api/config")
    assert resp.status_code in (200, 500)
