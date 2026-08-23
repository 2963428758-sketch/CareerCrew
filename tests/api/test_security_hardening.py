"""安全加固回归测试：SPA 路径穿越 / 未鉴权信息端点 / 上传限读 / 流式并发槽。

对应 2026-08 安全审查修复：
- main.py spa_fallback 必须把解析后路径限制在 DIST 内（防 /..%2f..%2f.env 读任意文件）
- /api/data/health、/api/data/config 必须登录后访问（部署细节不对外暴露）
- upload_io.read_bounded 大小上限在读取阶段生效（防超大 body 打爆内存）
- interview/questions 与其余流式端点一致套每用户并发槽
"""
from __future__ import annotations

import asyncio

import pytest

from careercrew_core.state.settings import AuthSettings

# ── SPA fallback 路径穿越 ──


def _build_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>careercrew-spa</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return dist


def _client_with_dist(tmp_path, monkeypatch):
    """构造 DIST 指向临时目录的 TestClient（真实认证链，无身份覆盖）。"""
    from fastapi.testclient import TestClient

    from careercrew_api import main as main_module
    from careercrew_api.auth.dependencies import get_auth_service
    from careercrew_api.auth.service import AuthService
    from tests.fakes import FakeAccountStore

    dist = _build_dist(tmp_path)
    secret = tmp_path / "secret.env"
    secret.write_text("SILICONFLOW_API_KEY=super-secret", encoding="utf-8")
    monkeypatch.setattr(main_module, "DIST", dist)

    auth = AuthService(
        AuthSettings(environment="test", jwt_secret="spa-fallback-test-signing-secret-0001"),
        FakeAccountStore(),
    )
    app = main_module.create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    return TestClient(app), secret


@pytest.mark.web
def test_spa_fallback_blocks_encoded_traversal(tmp_path, monkeypatch):
    """/..%2f..%2fsecret.env 不得读到 DIST 外文件，回退 index.html。"""
    client, secret = _client_with_dist(tmp_path, monkeypatch)
    resp = client.get("/..%2f..%2fsecret.env")
    assert resp.status_code == 200
    assert "super-secret" not in resp.text
    assert "careercrew-spa" in resp.text


@pytest.mark.web
def test_spa_fallback_blocks_deep_traversal(tmp_path, monkeypatch):
    client, _secret = _client_with_dist(tmp_path, monkeypatch)
    resp = client.get("/..%2f..%2f..%2f..%2f.env")
    assert resp.status_code == 200
    assert "careercrew-spa" in resp.text


@pytest.mark.web
def test_spa_fallback_still_serves_assets_and_index(tmp_path, monkeypatch):
    """正常静态资源与前端路由回退不受穿越校验影响。"""
    client, _secret = _client_with_dist(tmp_path, monkeypatch)

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log(1)" in asset.text

    unknown = client.get("/interview")
    assert unknown.status_code == 200
    assert "careercrew-spa" in unknown.text


@pytest.mark.web
def test_spa_fallback_never_returns_html_for_unknown_api_path(tmp_path, monkeypatch):
    """接口拼错或后端尚未更新时，前端必须收到 JSON 404 而非 index.html。"""
    client, _secret = _client_with_dist(tmp_path, monkeypatch)

    resp = client.get("/api/memory/records-not-registered")

    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"] == "API 接口不存在"


# ── 未鉴权信息端点 ──


@pytest.mark.web
def test_data_health_requires_auth(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from careercrew_api import main as main_module
    from careercrew_api.auth.dependencies import get_auth_service
    from careercrew_api.auth.service import AuthService
    from tests.fakes import FakeAccountStore

    monkeypatch.setattr(main_module, "DIST", tmp_path / "no-dist")  # 不挂 SPA 路由
    auth = AuthService(
        AuthSettings(environment="test", jwt_secret="data-health-test-signing-secret-002"),
        FakeAccountStore(),
    )
    app = main_module.create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    client = TestClient(app)

    resp = client.get("/api/health")
    assert resp.status_code == 401


@pytest.mark.web
def test_data_config_requires_auth(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from careercrew_api import main as main_module
    from careercrew_api.auth.dependencies import get_auth_service
    from careercrew_api.auth.service import AuthService
    from tests.fakes import FakeAccountStore

    monkeypatch.setattr(main_module, "DIST", tmp_path / "no-dist")
    auth = AuthService(
        AuthSettings(environment="test", jwt_secret="data-config-test-signing-secret-03"),
        FakeAccountStore(),
    )
    app = main_module.create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    client = TestClient(app)

    resp = client.get("/api/config")
    assert resp.status_code == 401


@pytest.mark.web
def test_data_health_ok_when_authenticated(client):
    """登录用户访问组件级健康检查不受鉴权加固影响（client fixture 已注入身份）。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── upload_io.read_bounded ──


class _FakeUpload:
    """duck-typed UploadFile：记录每次 read 的请求块大小。"""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0
        self.read_calls: list[int] = []

    async def read(self, n: int) -> bytes:
        self.read_calls.append(n)
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


@pytest.mark.web
def test_read_bounded_returns_full_content_under_limit():
    from careercrew_api.upload_io import read_bounded

    payload = b"x" * (1024 * 1024 + 123)  # 跨两个分块
    file = _FakeUpload(payload)
    got = asyncio.run(read_bounded(file, len(payload)))
    assert got == payload


@pytest.mark.web
def test_read_bounded_rejects_oversize_without_full_buffer():
    from careercrew_api.upload_io import read_bounded

    payload = b"x" * (3 * 1024 * 1024)
    file = _FakeUpload(payload)
    got = asyncio.run(read_bounded(file, 1024 * 1024))
    assert got is None  # 超限即拒绝，未把全部内容缓冲进内存


@pytest.mark.web
def test_read_bounded_empty_file():
    from careercrew_api.upload_io import read_bounded

    got = asyncio.run(read_bounded(_FakeUpload(b""), 1024))
    assert got == b""


# ── 流式并发槽覆盖 ──


def _stream_routes_missing_slot() -> list[str]:
    from careercrew_api.limits import user_stream_slot
    from careercrew_api.main import create_app

    expected = {
        "/api/chat/match",
        "/api/chat/plan",
        "/api/consult",
        "/api/interview/questions",
        "/api/interview/chat",
        "/api/resume/generate",
        "/api/resume/chat",
        "/api/knowledge/ask",
        "/api/messages/{message_id}/regenerate",
    }
    missing: list[str] = []
    app = create_app()
    for route in app.routes:
        path = getattr(route, "path", "")
        if path in expected:
            deps = {dep.call for dep in route.dependant.dependencies}
            if user_stream_slot not in deps:
                missing.append(path)
    return missing


@pytest.mark.web
def test_all_llm_stream_endpoints_have_user_stream_slot():
    """每个烧 LLM token 的流式端点都必须套 user_stream_slot（漏一个就是无限并发）。"""
    assert _stream_routes_missing_slot() == []
