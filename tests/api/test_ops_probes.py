"""运维探针（/healthz /readyz）、request_id 关联、每用户流式并发限制的验收测试。"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.web
class TestHealthProbes:
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
