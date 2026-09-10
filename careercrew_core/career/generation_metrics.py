"""Privacy-safe telemetry for career content generation.

Only allow-listed operational metadata is accepted or persisted.  Prompts,
generated text, resume/JD excerpts, entity ids, and free-form errors are absent
from the event contract by design.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated, Literal, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from careercrew_core.pg_pool import get_shared_pool

OwnerId = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=64)
]
ModelName = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)
]
GenerationFeature: TypeAlias = Literal[
    "ats_check", "gap_analysis", "application_kit", "intel_brief", "interview_review"
]
GenerationSource: TypeAlias = Literal["llm", "template", "rules"]
FallbackReason: TypeAlias = Literal[
    "no_llm", "missing_input", "invalid_json", "schema_validation", "provider_error", "empty_output"
]

_owner_adapter = TypeAdapter(OwnerId)
_feature_adapter = TypeAdapter(GenerationFeature)


class GenerationMetricInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    owner_id: OwnerId
    feature: GenerationFeature
    source: GenerationSource
    fallback_reason: FallbackReason | None = None
    model: ModelName | None = None
    latency_ms: Annotated[int, Field(strict=True, ge=0, le=3_600_000)]
    input_tokens: Annotated[int, Field(strict=True, ge=0)] | None = None
    output_tokens: Annotated[int, Field(strict=True, ge=0)] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _percentile_cont(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    fraction = index - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 2)


class GenerationMetricsStore:
    """Persist and aggregate owner-scoped generation metadata."""

    def __init__(self, dsn: str = "", pool=None):
        self.pool = pool or get_shared_pool(dsn)

    def record(self, event: GenerationMetricInput) -> str:
        event_id = str(uuid4())
        with self.pool.connection() as conn:
            conn.execute(
                """INSERT INTO career_generation_events
                   (id, owner_id, feature, source, fallback_reason, model, latency_ms,
                    input_tokens, output_tokens, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    event_id,
                    event.owner_id,
                    event.feature,
                    event.source,
                    event.fallback_reason,
                    event.model,
                    event.latency_ms,
                    event.input_tokens,
                    event.output_tokens,
                    event.created_at.isoformat(),
                ),
            )
        return event_id

    def aggregate(self, owner_id: str, feature: GenerationFeature | None = None) -> dict:
        owner_id = _owner_adapter.validate_python(owner_id, strict=True)
        if feature is not None:
            feature = _feature_adapter.validate_python(feature, strict=True)

        sql = (
            "SELECT source, fallback_reason, latency_ms, input_tokens, output_tokens "
            "FROM career_generation_events WHERE owner_id=%s"
        )
        params: tuple[object, ...] = (owner_id,)
        if feature is not None:
            sql += " AND feature=%s"
            params += (feature,)
        with self.pool.connection() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

        by_source: dict[str, int] = {}
        by_reason: dict[str, int] = {}
        latencies: list[int] = []
        input_tokens: list[int] = []
        output_tokens: list[int] = []
        for row in rows:
            source = str(row["source"])
            by_source[source] = by_source.get(source, 0) + 1
            reason = row.get("fallback_reason")
            if reason:
                reason = str(reason)
                by_reason[reason] = by_reason.get(reason, 0) + 1
            if row.get("latency_ms") is not None:
                latencies.append(int(row["latency_ms"]))
            if row.get("input_tokens") is not None:
                input_tokens.append(int(row["input_tokens"]))
            if row.get("output_tokens") is not None:
                output_tokens.append(int(row["output_tokens"]))

        total = len(rows)
        fallback_count = sum(by_reason.values())
        return {
            "owner_id": owner_id,
            "feature": feature,
            "total": total,
            "by_source": by_source,
            "by_reason": by_reason,
            "fallback_count": fallback_count,
            "success_count": total - fallback_count,
            "fallback_rate": round(fallback_count / total, 4) if total else 0.0,
            "p95_latency_ms": _percentile_cont(latencies, 0.95),
            "latency_samples": len(latencies),
            "avg_input_tokens": round(sum(input_tokens) / len(input_tokens), 1)
            if input_tokens else None,
            "avg_output_tokens": round(sum(output_tokens) / len(output_tokens), 1)
            if output_tokens else None,
            "input_token_samples": len(input_tokens),
            "output_token_samples": len(output_tokens),
        }
