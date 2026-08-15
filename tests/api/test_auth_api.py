"""本地账号、访问 JWT 与刷新 Cookie API 回归测试。"""
from __future__ import annotations

import pytest


PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def auth_client(tmp_path):
    from fastapi.testclient import TestClient

    from careercrew_api.auth.dependencies import get_auth_service
    from careercrew_api.auth.service import AccountStore, AuthService
    from careercrew_core.state.settings import AuthSettings
    from careercrew_api.main import create_app

    settings = AuthSettings(
        environment="test",
        jwt_secret="test-signing-secret-that-is-long-enough-for-repeatable-api-tests",
        account_db_path=str(tmp_path / "accounts.db"),
    )
    service = AuthService(settings, AccountStore(settings.account_db_path))
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    with TestClient(app) as client:
        yield client


def _bootstrap(client, username: str = "admin") -> dict:
    response = client.post("/api/auth/bootstrap", json={"username": username, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.web
def test_bootstrap_status_only_reports_whether_first_admin_can_be_created(auth_client):
    available = auth_client.get("/api/auth/bootstrap")
    assert available.status_code == 200
    assert available.json() == {"available": True}

    _bootstrap(auth_client)

    unavailable = auth_client.get("/api/auth/bootstrap")
    assert unavailable.status_code == 200
    assert unavailable.json() == {"available": False}


@pytest.mark.web
def test_password_login_protects_me_and_never_returns_refresh_token(auth_client):
    user = _bootstrap(auth_client)
    assert user == {"id": "u_001", "username": "admin", "role": "admin"}

    unauthorized = auth_client.get("/api/auth/me")
    assert unauthorized.status_code == 401

    login = auth_client.post("/api/auth/token", json={"username": "admin", "password": PASSWORD})
    assert login.status_code == 200
    payload = login.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"] == user
    assert "refresh" not in payload
    assert "password" not in payload
    assert "httponly" in login.headers["set-cookie"].lower()
    assert "samesite=lax" in login.headers["set-cookie"].lower()

    me = auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {payload['access_token']}"})
    assert me.status_code == 200
    assert me.json() == user


@pytest.mark.web
def test_refresh_cookie_rotates_and_logout_invalidates_session(auth_client):
    _bootstrap(auth_client)
    login = auth_client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    old_cookie = auth_client.cookies.get("careercrew_refresh")
    assert old_cookie

    refresh = auth_client.post("/api/auth/refresh")
    assert refresh.status_code == 200
    new_cookie = auth_client.cookies.get("careercrew_refresh")
    assert new_cookie and new_cookie != old_cookie

    auth_client.cookies.set("careercrew_refresh", old_cookie, path="/api/auth")
    replay = auth_client.post("/api/auth/refresh")
    assert replay.status_code == 401

    # 恢复新 cookie 后验证 logout 确实撤销服务端会话，而非仅删除浏览器值。
    auth_client.cookies.set("careercrew_refresh", new_cookie, path="/api/auth")
    logout = auth_client.post("/api/auth/logout")
    assert logout.status_code == 204
    auth_client.cookies.set("careercrew_refresh", new_cookie, path="/api/auth")
    assert auth_client.post("/api/auth/refresh").status_code == 401


@pytest.mark.web
def test_only_administrator_can_create_accounts(auth_client):
    _bootstrap(auth_client)
    admin_login = auth_client.post("/api/auth/token", json={"username": "admin", "password": PASSWORD}).json()
    admin_headers = {"Authorization": f"Bearer {admin_login['access_token']}"}

    created = auth_client.post(
        "/api/auth/users",
        json={"username": "member", "password": PASSWORD, "role": "user"},
        headers=admin_headers,
    )
    assert created.status_code == 201
    member = created.json()
    assert member["role"] == "user"
    assert member["id"] != "u_001"
    assert "password" not in member

    member_login = auth_client.post("/api/auth/token", json={"username": "member", "password": PASSWORD}).json()
    member_headers = {"Authorization": f"Bearer {member_login['access_token']}"}
    forbidden = auth_client.post(
        "/api/auth/users", json={"username": "other", "password": PASSWORD}, headers=member_headers
    )
    assert forbidden.status_code == 403


@pytest.mark.web
def test_production_startup_requires_explicit_auth_secret(tmp_path, monkeypatch):
    from careercrew_api.main import create_app
    from careercrew_core.state import settings as settings_module
    from careercrew_core.state.settings import SettingsError

    config = tmp_path / "settings.yaml"
    config.write_text(
        "auth:\n  environment: production\n  jwt_secret: ''\n  cookie_secure: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_module, "DEFAULT_CONFIG_PATH", config)
    with pytest.raises(SettingsError, match="auth.jwt_secret"):
        create_app()
