"""Prometheus scrape smoke test。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from careercrew_api.main import create_app
from careercrew_core.observability.metrics import get_metrics_registry


def test_metrics_endpoint_returns_prometheus_text() -> None:
    registry = get_metrics_registry()
    registry.inc_sse_interrupted()
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "careercrew_sse_interrupted_total" in response.text


def test_metrics_endpoint_requires_configured_scrape_token(monkeypatch) -> None:
    monkeypatch.setenv("CAREERCREW_METRICS_TOKEN", "metrics-secret")
    app = create_app()

    with TestClient(app) as client:
        assert client.get("/metrics").status_code == 401
        response = client.get(
            "/metrics",
            headers={"Authorization": "Bearer metrics-secret"},
        )

    assert response.status_code == 200
