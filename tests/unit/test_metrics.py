"""低基数 Prometheus 文本指标。"""
from __future__ import annotations

from careercrew_core.observability.metrics import MetricsRegistry


def test_metrics_render_covers_http_llm_rag_upload_tool_and_sse() -> None:
    registry = MetricsRegistry()
    registry.observe_http("GET", "/api/usage/summary", 200, 0.125)
    registry.observe_llm("chat", "completed", 0.5, input_tokens=10, output_tokens=5)
    registry.inc_rag("hit")
    registry.inc_rag("query")
    registry.inc_upload("queued")
    registry.inc_tool("completed")
    registry.inc_sse_interrupted()
    registry.set_upload_backlog(3)

    rendered = registry.render()

    assert "careercrew_http_requests_total" in rendered
    assert "careercrew_llm_requests_total" in rendered
    assert "careercrew_rag_operations_total" in rendered
    assert "careercrew_upload_tasks_total" in rendered
    assert "careercrew_tool_calls_total" in rendered
    assert "careercrew_sse_interrupted_total 1" in rendered
    assert "careercrew_upload_backlog 3" in rendered
    assert "input_tokens" not in rendered
    assert "alice" not in rendered


def test_metrics_labels_are_normalized_and_do_not_accept_user_ids() -> None:
    registry = MetricsRegistry()
    registry.observe_http("GET", "/api/users/1234567890", 500, 1.0)
    registry.observe_llm("module with spaces", "failed", 1.0)

    rendered = registry.render()

    assert "1234567890" not in rendered
    assert "module with spaces" not in rendered
