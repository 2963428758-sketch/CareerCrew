"""本地账号、访问 JWT 与刷新 Cookie API 回归测试。"""
from __future__ import annotations

import pytest


PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def auth_client(tmp_path):
    from fastapi.testclient import TestClient

    from careercrew_api.auth.dependencies import get_auth_service
    from careercrew_api.auth.service import AuthService
    from careercrew_api.auth.store import create_account_store
    from careercrew_core.state.settings import AuthSettings
    from careercrew_api.main import create_app

    settings = AuthSettings(
        environment="test",
        backend="sqlite",
        jwt_secret="test-signing-secret-that-is-long-enough-for-repeatable-api-tests",
        account_db_path=str(tmp_path / "accounts.db"),
    )
    service = AuthService(settings, create_account_store(settings))
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
        "auth:\n  environment: production\n  backend: postgres\n"
        "  database_url: 'postgresql://careercrew:careercrew@localhost:5432/careercrew'\n"
        "  jwt_secret: ''\n  cookie_secure: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_module, "DEFAULT_CONFIG_PATH", config)
    monkeypatch.setattr(settings_module, "load_dotenv", lambda: None)
    with pytest.raises(SettingsError, match="auth.jwt_secret"):
        create_app()


@pytest.mark.web
def test_admin_lists_patches_and_disables_users(auth_client):
    _bootstrap(auth_client)
    admin_headers = {"Authorization": f"Bearer {auth_client.post('/api/auth/token', json={'username': 'admin', 'password': PASSWORD}).json()['access_token']}"}

    created = auth_client.post(
        "/api/auth/users", json={"username": "member", "password": PASSWORD}, headers=admin_headers
    )
    assert created.status_code == 201
    member_id = created.json()["id"]

    listed = auth_client.get("/api/auth/users", headers=admin_headers)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 2
    assert {u["username"] for u in body["items"]} == {"admin", "member"}

    member_token = auth_client.post("/api/auth/token", json={"username": "member", "password": PASSWORD}).json()["access_token"]
    member_headers = {"Authorization": f"Bearer {member_token}"}

    patched = auth_client.patch(
        f"/api/auth/users/{member_id}", json={"status": "disabled"}, headers=admin_headers
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "disabled"
    # 禁用立即生效：旧 access token 失效、登录被拒
    assert auth_client.get("/api/auth/me", headers=member_headers).status_code == 401
    assert auth_client.post("/api/auth/token", json={"username": "member", "password": PASSWORD}).status_code == 401

    reenabled = auth_client.patch(
        f"/api/auth/users/{member_id}", json={"status": "active"}, headers=admin_headers
    )
    assert reenabled.status_code == 200 and reenabled.json()["status"] == "active"


@pytest.mark.web
def test_admin_self_and_last_admin_guards(auth_client):
    _bootstrap(auth_client)
    admin_token = auth_client.post("/api/auth/token", json={"username": "admin", "password": PASSWORD}).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    # 唯一 admin 自改 → 系统级不变量 409（禁止失去最后管理员）
    assert auth_client.patch("/api/auth/users/u_001", json={"status": "disabled"}, headers=admin_headers).status_code == 409
    assert auth_client.patch("/api/auth/users/u_001", json={"role": "user"}, headers=admin_headers).status_code == 409
    assert auth_client.patch("/api/auth/users/not-exist", json={"status": "disabled"}, headers=admin_headers).status_code == 404
    # 有第二个 admin 后，第二个 admin 自改 → 403（SelfAdmin）
    assert auth_client.post("/api/auth/users", json={"username": "second", "password": PASSWORD, "role": "admin"}, headers=admin_headers).status_code == 201
    second_id = auth_client.get("/api/auth/users", headers=admin_headers).json()["items"][1]["id"]
    second_token = auth_client.post("/api/auth/token", json={"username": "second", "password": PASSWORD}).json()["access_token"]
    second_headers = {"Authorization": f"Bearer {second_token}"}
    assert auth_client.patch(f"/api/auth/users/{second_id}", json={"status": "disabled"}, headers=second_headers).status_code == 403


@pytest.mark.web
def test_reset_password_and_change_own_password(auth_client):
    _bootstrap(auth_client)
    admin_headers = {"Authorization": f"Bearer {auth_client.post('/api/auth/token', json={'username': 'admin', 'password': PASSWORD}).json()['access_token']}"}
    member_id = auth_client.post("/api/auth/users", json={"username": "member", "password": PASSWORD}, headers=admin_headers).json()["id"]

    reset = auth_client.post(
        f"/api/auth/users/{member_id}/reset-password",
        json={"password": "another-password-456"}, headers=admin_headers,
    )
    assert reset.status_code == 200 and reset.json() == {"ok": True}
    assert auth_client.post("/api/auth/token", json={"username": "member", "password": PASSWORD}).status_code == 401
    member_token = auth_client.post("/api/auth/token", json={"username": "member", "password": "another-password-456"}).json()["access_token"]
    member_headers = {"Authorization": f"Bearer {member_token}"}

    change = auth_client.post(
        "/api/auth/password",
        json={"old_password": "another-password-456", "new_password": "third-password-789"},
        headers=member_headers,
    )
    assert change.status_code == 200 and change.json() == {"ok": True}
    # 改密后旧 access token 已按 token_version 失效，需重新登录
    assert auth_client.get("/api/auth/users", headers=member_headers).status_code == 401
    fresh_token = auth_client.post("/api/auth/token", json={"username": "member", "password": "third-password-789"}).json()["access_token"]
    fresh_headers = {"Authorization": f"Bearer {fresh_token}"}
    # 普通用户不能调用管理端点
    assert auth_client.get("/api/auth/users", headers=fresh_headers).status_code == 403


@pytest.mark.web
def test_login_lock_returns_429_with_retry_after(auth_client):
    _bootstrap(auth_client)
    for _ in range(5):
        auth_client.post("/api/auth/token", json={"username": "admin", "password": "wrong-password-123"})
    locked = auth_client.post("/api/auth/token", json={"username": "admin", "password": PASSWORD})
    assert locked.status_code == 429
    assert locked.headers.get("retry-after")
