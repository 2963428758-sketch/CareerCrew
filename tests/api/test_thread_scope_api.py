"""会话检索范围（retrieval_scope）持久化 API 回归测试。

覆盖：PATCH 写入与列表返回、历史线程回退 None、仅改标题不丢范围、
非法范围 422、跨用户隔离（参考 test_tenant_isolation_api.py 的双用户模式）。
"""
from __future__ import annotations

import pytest


def test_patch_scope_persists_and_lists(client):
    client.post("/api/threads", json={"thread_id": "k-scope-1", "module": "knowledge"})
    resp = client.patch("/api/threads/k-scope-1", json={
        "retrieval_scope": {"type": "category", "category_id": "resume"}})
    assert resp.status_code == 200
    rows = client.get("/api/threads", params={"module": "knowledge"}).json()
    row = next(r for r in rows if r["thread_id"] == "k-scope-1")
    assert row["retrieval_scope"] == {"type": "category", "category_id": "resume"}


def test_legacy_thread_scope_none(client):
    client.post("/api/threads", json={"thread_id": "k-legacy", "module": "knowledge"})
    rows = client.get("/api/threads", params={"module": "knowledge"}).json()
    assert next(r for r in rows if r["thread_id"] == "k-legacy")["retrieval_scope"] is None


def test_patch_title_preserves_scope(client):
    client.post("/api/threads", json={"thread_id": "k-pres", "module": "knowledge"})
    client.patch("/api/threads/k-pres", json={"retrieval_scope": {"type": "all"}})
    client.patch("/api/threads/k-pres", json={"title": "新标题"})
    rows = client.get("/api/threads", params={"module": "knowledge"}).json()
    assert next(r for r in rows if r["thread_id"] == "k-pres")["retrieval_scope"] == {
        "type": "all"}


def test_invalid_scope_rejected(client):
    assert client.patch("/api/threads/k-x", json={
        "retrieval_scope": {"type": "category", "category_id": ""}}).status_code == 422
    assert client.patch("/api/threads/k-x", json={
        "retrieval_scope": {"type": "bogus"}}).status_code == 422


@pytest.fixture
def tenant_api(tmp_path, monkeypatch):
    """双账号客户端（模式同 test_tenant_isolation_api.tenant_api）。"""
    from fastapi.testclient import TestClient

    from careercrew_api.auth.dependencies import get_auth_service
    from careercrew_api.auth.service import AuthService
    from careercrew_api.auth.store import create_account_store
    from careercrew_api.deps import get_runtime_dep
    from careercrew_api.main import create_app
    from careercrew_core.state.settings import AuthSettings
    from tests.api.conftest import FakeRuntime

    settings = AuthSettings(
        environment="test",
        backend="sqlite",
        jwt_secret="thread-scope-test-signing-secret-with-enough-entropy",
        account_db_path=str(tmp_path / "accounts.db"),
    )
    auth = AuthService(settings, create_account_store(settings))
    runtime = FakeRuntime()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    client = TestClient(app)

    password = "correct-horse-battery-staple"
    admin = client.post(
        "/api/auth/bootstrap", json={"username": "alice", "password": password}
    ).json()
    admin_login = client.post(
        "/api/auth/token", json={"username": "alice", "password": password}
    ).json()
    admin_headers = {"Authorization": f"Bearer {admin_login['access_token']}"}
    client.post(
        "/api/auth/users", json={"username": "bob", "password": password, "role": "user"},
        headers=admin_headers,
    )
    bob_login = client.post(
        "/api/auth/token", json={"username": "bob", "password": password}
    ).json()
    bob_headers = {"Authorization": f"Bearer {bob_login['access_token']}"}
    return client, {"alice": admin_headers, "bob": bob_headers}, {
        "alice": admin["id"], "bob": bob_login["user"]["id"],
    }


def test_scope_isolated_between_users(tenant_api):
    client, headers, _ids = tenant_api
    client.post("/api/threads", json={"thread_id": "k-alice", "module": "knowledge"},
                headers=headers["alice"])
    client.patch("/api/threads/k-alice", json={
        "retrieval_scope": {"type": "category", "category_id": "interview"}},
        headers=headers["alice"])
    assert client.patch("/api/threads/k-alice", json={
        "retrieval_scope": {"type": "all"}}, headers=headers["bob"]).status_code == 404
    rows = client.get("/api/threads", params={"module": "knowledge"},
                      headers=headers["alice"]).json()
    assert next(r for r in rows if r["thread_id"] == "k-alice")["retrieval_scope"]["category_id"] == "interview"


def test_create_thread_with_scope(client):
    resp = client.post("/api/threads", json={
        "thread_id": "k-new", "module": "knowledge",
        "retrieval_scope": {"type": "category", "category_id": "job"}})
    assert resp.status_code == 200
    rows = client.get("/api/threads", params={"module": "knowledge"}).json()
    assert next(r for r in rows if r["thread_id"] == "k-new")["retrieval_scope"] == {
        "type": "category", "category_id": "job"}
