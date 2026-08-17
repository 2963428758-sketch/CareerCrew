"""头像上传/读取端点回归测试（OSS 未配置时的本地回退路径 + 校验规则）。"""
from __future__ import annotations

import pytest

from tests.fakes import FakeAccountStore

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def avatar_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from careercrew_api.auth.dependencies import get_auth_service, get_current_user
    from careercrew_api.auth.service import AuthService
    from careercrew_api.main import create_app
    from careercrew_core.state.settings import AuthSettings

    settings = AuthSettings(
        environment="test",
        jwt_secret="test-signing-secret-that-is-long-enough-for-repeatable-api-tests",
    )
    service = AuthService(settings, FakeAccountStore())
    service.store.create_first_admin("admin", "hashed")

    import careercrew_api.routers.auth as auth_router

    # 本地回退路径测试：关闭 OSS 配置（与 .env 是否存在无关），头像目录指向 tmp
    monkeypatch.setattr(auth_router, "oss_config", lambda: None)
    monkeypatch.setattr(auth_router, "AVATAR_ROOT", tmp_path / "avatars")

    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u_001", "username": "admin", "role": "admin",
    }
    with TestClient(app) as client:
        yield client, service, tmp_path


@pytest.mark.web
def test_upload_avatar_local_fallback_and_read_back(avatar_client):
    client, service, _tmp = avatar_client
    upload = client.post(
        "/api/auth/avatar",
        files={"file": ("me.png", PNG_BYTES, "image/png")},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json() == {"ok": True}

    ref = service.store.accounts["u_001"]["avatar"]
    assert ref.startswith("local:u_001/") and ref.endswith(".png")

    got = client.get("/api/auth/avatar/u_001")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert got.content == PNG_BYTES


@pytest.mark.web
def test_avatar_rejects_bad_type_and_oversize(avatar_client):
    client, _service, _tmp = avatar_client
    bad = client.post(
        "/api/auth/avatar",
        files={"file": ("evil.txt", b"hello", "text/plain")},
    )
    assert bad.status_code == 400

    big = client.post(
        "/api/auth/avatar",
        files={"file": ("big.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
    )
    assert big.status_code == 400


@pytest.mark.web
def test_avatar_404_without_avatar(avatar_client):
    client, _service, _tmp = avatar_client
    got = client.get("/api/auth/avatar/u_001")
    assert got.status_code == 404
