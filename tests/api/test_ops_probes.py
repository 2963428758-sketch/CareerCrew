"""运维探针（/healthz /readyz）、request_id 关联、每用户流式并发限制的验收测试。"""
from __future__ import annotations

import asyncio
import logging

import pytest


@pytest.mark.web
class TestHealthProbes:
    @staticmethod
    def _install_share_dependency_fakes(client):
        """边界中间件测试不应因开发机数据库停机而变成集成测试。"""
        from careercrew_api.routers import career
        from careercrew_api.routers.preparation import get_preparation_store

        class MissingShareStore:
            def resolve_share(self, _token):
                return None

        class UnusedPreparationStore:
            pass

        client.app.dependency_overrides[career._store_dep] = lambda: MissingShareStore()
        client.app.dependency_overrides[get_preparation_store] = lambda: UnusedPreparationStore()

    @staticmethod
    def _remove_share_dependency_fakes(client):
        from careercrew_api.routers import career
        from careercrew_api.routers.preparation import get_preparation_store

        client.app.dependency_overrides.pop(career._store_dep, None)
        client.app.dependency_overrides.pop(get_preparation_store, None)

    def test_healthz_liveness(self, client):
        """liveness 不触碰依赖，进程存活即 200。"""
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_readyz_schema(self, client):
        """readiness 返回结构化检查项；每项 ok 或 unavailable（CI 有真库无 qdrant → 部分可用）。"""
        resp = client.get("/readyz")
        assert resp.status_code in (200, 503)
        body = resp.json()
        assert set(body["checks"]) == {"postgres", "qdrant"}
        values = body["checks"].values()
        assert all(v == "ok" or v.startswith("unavailable") for v in values)
        if resp.status_code == 503:
            assert body["status"] == "not_ready"
            assert any(v.startswith("unavailable") for v in values)

    def test_request_id_echo_and_generate(self, client):
        """X-Request-ID 透传；未携带时生成并回写。"""
        echoed = client.get("/healthz", headers={"X-Request-ID": "req-test-001"})
        assert echoed.headers["X-Request-ID"] == "req-test-001"

        generated = client.get("/healthz")
        rid = generated.headers["X-Request-ID"]
        assert rid and rid != "-" and len(rid) == 12

    def test_share_paths_are_redacted_in_request_logs(self, client, caplog):
        """公开分享 bearer 令牌不得进入应用访问日志。"""
        token = "plain-share-token-must-not-be-logged"
        self._install_share_dependency_fakes(client)
        try:
            with caplog.at_level("INFO", logger="careercrew_api"):
                client.get(f"/api/career/share/{token}")
                client.get(f"/share/{token}")
        finally:
            self._remove_share_dependency_fakes(client)

        messages = [record.getMessage() for record in caplog.records
                    if record.name == "careercrew_api"]
        assert token not in "\n".join(messages)
        assert any("/api/career/share/[redacted]" in message for message in messages)
        assert any("/share/[redacted]" in message for message in messages)

    def test_uvicorn_access_log_redacts_share_bearer_token(self):
        """服务器默认 access logger 也不能绕过应用中间件泄露 bearer 令牌。"""
        from careercrew_api.main import _UvicornSharePathFilter

        token = "uvicorn-must-not-log-this-token"
        record = logging.LogRecord(
            "uvicorn.access", logging.INFO, __file__, 1,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:1", "GET", f"/api/career/share/{token}?preview=1", "1.1", 200),
            None,
        )
        access_logger = logging.getLogger("uvicorn.access")
        assert any(isinstance(item, _UvicornSharePathFilter) for item in access_logger.filters)
        assert _UvicornSharePathFilter().filter(record) is True
        assert token not in record.getMessage()
        assert "/api/career/share/[redacted]" in record.getMessage()

    @pytest.mark.parametrize("path", [
        "/api/career/share/a-secret-token",
        "/share/a-secret-token",
    ])
    def test_all_share_responses_have_privacy_headers(self, client, path):
        """API JSON、错误响应和 SPA HTML 都由全局边界补齐同一组隐私头。"""
        self._install_share_dependency_fakes(client)
        try:
            response = client.get(path)
        finally:
            self._remove_share_dependency_fakes(client)
        assert "no-store" in response.headers["cache-control"]
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.web
class TestUserStreamLimit:
    def _scenario(self, limit: int):
        from careercrew_api.limits import MAX_STREAMS_PER_USER, _sems, user_stream_slot

        async def run():
            _sems.clear()
            user = {"id": "u_limit_test", "username": "u", "role": "user"}
            assert MAX_STREAMS_PER_USER == limit

            gens = []
            for _ in range(limit):
                g = user_stream_slot(current_user=user)
                await g.__anext__()  # 进入 yield：槽位占用
                gens.append(g)

            with pytest.raises(Exception) as exc_info:
                await user_stream_slot(current_user=user).__anext__()
            assert getattr(exc_info.value, "status_code", None) == 429

            for g in gens:  # 释放后可再次进入
                await g.aclose()
            g = user_stream_slot(current_user=user)
            await g.__anext__()
            await g.aclose()

        asyncio.run(run())

    def test_limit_two(self):
        self._scenario(2)
