"""browser 路由单元测试：CDP 状态探测与启动。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from careercrew_api.auth.dependencies import get_current_user
from careercrew_api.main import create_app
from careercrew_api.routers import browser

_BROWSER_ENDPOINTS = (
    ("get", "/api/browser/cdp-status"),
    ("post", "/api/browser/launch-cdp"),
    ("get", "/api/browser/cdp-command"),
)


def _authenticated_client(host: str = "127.0.0.1") -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": "local-user", "role": "user"}
    return TestClient(app, client=(host, 50001))


def test_get_cdp_status_connected(monkeypatch) -> None:
    monkeypatch.setattr(browser, "_check_cdp_alive", lambda url, timeout=1.2: (True, [
        {"url": "https://www.zhipin.com/web/geek/jobs"},
        {"url": "https://www.liepin.com/zhaopin"},
    ]))
    client = _authenticated_client()
    resp = client.get("/api/browser/cdp-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["boss_opened"] is True
    assert data["liepin_opened"] is True
    assert "start_chrome_cdp" in data["command"]


def test_get_cdp_status_disconnected(monkeypatch) -> None:
    monkeypatch.setattr(browser, "_check_cdp_alive", lambda url, timeout=1.2: (False, []))
    client = _authenticated_client()
    resp = client.get("/api/browser/cdp-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["boss_opened"] is False
    assert data["liepin_opened"] is False


def test_launch_cdp_already_running(monkeypatch) -> None:
    monkeypatch.setattr(browser, "_check_cdp_alive", lambda url, timeout=0.8: (True, []))
    client = _authenticated_client()
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
    client = _authenticated_client()
    resp = client.post("/api/browser/launch-cdp")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "launched"
    assert len(launched) == 1
    assert "start_chrome_cdp" in str(launched[0])


def test_get_cdp_command_for_authenticated_local_client() -> None:
    client = _authenticated_client()

    resp = client.get("/api/browser/cdp-command")

    assert resp.status_code == 200
    assert "start_chrome_cdp" in resp.json()["command"]


@pytest.mark.parametrize(("method", "path"), _BROWSER_ENDPOINTS)
def test_every_browser_route_requires_bearer_authentication(method: str, path: str) -> None:
    app = create_app()
    client = TestClient(app, client=("127.0.0.1", 50001))

    resp = getattr(client, method)(path)

    assert resp.status_code == 401


@pytest.mark.parametrize(("method", "path"), _BROWSER_ENDPOINTS)
def test_every_browser_route_rejects_non_loopback_before_browser_work(
    monkeypatch, method: str, path: str,
) -> None:
    cdp_calls = []
    launched = []

    def check_cdp_alive(url: str, timeout: float = 1.2):
        cdp_calls.append((url, timeout))
        return True, []

    monkeypatch.setattr(browser, "_check_cdp_alive", check_cdp_alive)
    monkeypatch.setattr(browser.subprocess, "Popen", lambda *args, **kwargs: launched.append((args, kwargs)))
    client = _authenticated_client("192.0.2.10")

    resp = getattr(client, method)(path)

    assert resp.status_code == 403
    assert cdp_calls == []
    assert launched == []


def test_browser_routes_accept_ipv4_mapped_loopback_client(monkeypatch) -> None:
    monkeypatch.setattr(browser, "_check_cdp_alive", lambda url, timeout=1.2: (False, []))
    client = _authenticated_client("::ffff:127.0.0.1")

    resp = client.get("/api/browser/cdp-status")

    assert resp.status_code == 200
