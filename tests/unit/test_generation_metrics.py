"""Privacy-safe career generation telemetry and owner-scoped aggregation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from careercrew_core.career.generation_metrics import (
    GenerationMetricInput,
    GenerationMetricsStore,
)
from tests.preparation_fakes import SqlitePreparationPool


@pytest.fixture
def metrics_store():
    pool = SqlitePreparationPool()
    pool.db.execute("""
        CREATE TABLE career_generation_events (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            feature TEXT NOT NULL,
            source TEXT NOT NULL,
            fallback_reason TEXT,
            model TEXT,
            latency_ms INTEGER NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            created_at TEXT NOT NULL
        )
    """)
    yield GenerationMetricsStore(pool=pool)
    pool.close()


def test_metric_input_rejects_content_and_free_text_failure_details() -> None:
    with pytest.raises(ValidationError):
        GenerationMetricInput.model_validate({
            "owner_id": "alice",
            "feature": "application_kit",
            "source": "template",
            "fallback_reason": "模型说出了用户手机号 13800138000",
            "latency_ms": 120,
            "prompt": "完整简历正文",
        })


def test_metric_input_uses_strict_numeric_fields() -> None:
    with pytest.raises(ValidationError):
        GenerationMetricInput.model_validate({
            "owner_id": "alice",
            "feature": "application_kit",
            "source": "llm",
            "latency_ms": "120",
        })


def test_store_aggregates_only_requested_owner_with_p95_and_optional_tokens(metrics_store) -> None:
    rows = [
        {"owner_id": "alice", "feature": "application_kit", "source": "llm",
         "latency_ms": 100, "input_tokens": 10, "output_tokens": 5},
        {"owner_id": "alice", "feature": "application_kit", "source": "template",
         "fallback_reason": "invalid_json", "latency_ms": 200},
        {"owner_id": "alice", "feature": "application_kit", "source": "template",
         "fallback_reason": "provider_error", "latency_ms": 300,
         "input_tokens": 30, "output_tokens": 15},
        {"owner_id": "alice", "feature": "intel_brief", "source": "rules",
         "fallback_reason": "missing_input", "latency_ms": 1000},
        {"owner_id": "bob", "feature": "application_kit", "source": "llm",
         "latency_ms": 9999, "input_tokens": 999, "output_tokens": 999},
    ]
    for row in rows:
        metrics_store.record(GenerationMetricInput.model_validate(row))

    result = metrics_store.aggregate("alice")

    assert result == {
        "owner_id": "alice",
        "feature": None,
        "total": 4,
        "by_source": {"llm": 1, "template": 2, "rules": 1},
        "by_reason": {"invalid_json": 1, "provider_error": 1, "missing_input": 1},
        "fallback_count": 3,
        "success_count": 1,
        "fallback_rate": 0.75,
        "p95_latency_ms": 895.0,
        "latency_samples": 4,
        "avg_input_tokens": 20.0,
        "avg_output_tokens": 10.0,
        "input_token_samples": 2,
        "output_token_samples": 2,
    }


def test_store_can_aggregate_one_feature_and_handles_no_rows(metrics_store) -> None:
    metrics_store.record(GenerationMetricInput(
        owner_id="alice",
        feature="application_kit",
        source="llm",
        latency_ms=80,
    ))
    metrics_store.record(GenerationMetricInput(
        owner_id="alice",
        feature="intel_brief",
        source="template",
        fallback_reason="empty_output",
        latency_ms=120,
    ))

    scoped = metrics_store.aggregate("alice", feature="application_kit")
    empty = metrics_store.aggregate("nobody")

    assert scoped["total"] == 1
    assert scoped["success_count"] == 1
    assert scoped["by_source"] == {"llm": 1}
    assert scoped["feature"] == "application_kit"
    assert empty["total"] == 0
    assert empty["success_count"] == 0
    assert empty["p95_latency_ms"] is None
    assert empty["fallback_rate"] == 0.0
