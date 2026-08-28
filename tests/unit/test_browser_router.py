"""browser 路由单元测试：CDP 状态探测与启动。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from careercrew_api.main import create_app
from careercrew_api.routers import browser


def test_get_cdp_status_connected(monkeypatch) -> None:
    monkeypatch.setattr(browser, "_check_cdp_alive", lambda url, timeout=1.2: (True, [
        {"url": "https://www.zhipin.com/web/geek/jobs"},
        {"url": "https://www.liepin.com/zhaopin"},
    ]))
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/browser/cdp-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["boss_opened"] is True
    assert data["liepin_opened"] is True
    assert "start_chrome_cdp" in data["command"]


def test_get_cdp_status_disconnected(monkeypatch) -> None:
    monkeypatch.setattr(browser, "_check_cdp_alive", lambda url, timeout=1.2: (False, []))
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/browser/cdp-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["boss_opened"] is False
    assert data["liepin_opened"] is False


def test_launch_cdp_already_running(monkeypatch) -> None:
    monkeypatch.setattr(browser, "_check_cdp_alive", lambda url, timeout=0.8: (True, []))
    app = create_app()
    client = TestClient(app)
    resp = client.post("/api/browser/launch-cdp")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "already_running"
    assert data["connected"] is True


def test_launch_cdp_triggers_process(monkeypatch) -> None:
    monkeypatch.setattr(browser, "_check_cdp_alive", lambda url, timeout=0.8: (False, []))
    launched = []

    class DummyProc:
        pass

    monkeypatch.setattr(browser.subprocess, "Popen", lambda cmd, **k: launched.append(cmd) or DummyProc())
    app = create_app()
    client = TestClient(app)
    resp = client.post("/api/browser/launch-cdp")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "launched"
    assert len(launched) == 1
    assert "start_chrome_cdp" in str(launched[0])
