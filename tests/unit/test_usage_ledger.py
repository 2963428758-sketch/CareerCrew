"""账号级用量、价格卡和脱敏边界。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.usage.ledger import (
    PriceBook,
    UsageLedger,
    UsageValidationError,
)


def _ledger() -> UsageLedger:
    prices = PriceBook(
        {
            "openai:gpt-test": {
                "input_per_million": Decimal("2"),
                "output_per_million": Decimal("4"),
            }
        },
        version="prices-2026-09",
    )
    return UsageLedger(FakeMemoryDb(), pricing=prices)


def test_pricing_version_math_unknown_price_and_idempotent_source_event() -> None:
    ledger = _ledger()
    first = ledger.record(
        "alice", module="chat", provider="openai", model="gpt-test",
        input_tokens=1000, output_tokens=500, source_event_id="run-1",
    )
    again = ledger.record(
        "alice", module="chat", provider="openai", model="gpt-test",
        input_tokens=1000, output_tokens=500, source_event_id="run-1",
    )
    unknown = ledger.record(
        "alice", module="chat", provider="other", model="private-model",
        input_tokens=2, output_tokens=3, source_event_id="run-2",
    )

    assert first["id"] == again["id"]
    assert first["pricing_version"] == "prices-2026-09"
    assert first["estimated_cost_usd"] == "0.004"
    assert unknown["estimated_cost_usd"] is None
    assert unknown["pricing_status"] == "unknown"
    assert ledger.summary("alice")["events"] == 2


def test_summary_is_owner_and_module_scoped_without_raw_event_body() -> None:
    ledger = _ledger()
    ledger.record("alice", module="chat", provider="openai", model="gpt-test", input_tokens=10, output_tokens=5)
    ledger.record("alice", module="resume", provider="openai", model="gpt-test", input_tokens=30, output_tokens=15)
    ledger.record("bob", module="chat", provider="openai", model="gpt-test", input_tokens=900, output_tokens=900)

    result = ledger.summary("alice", module="resume")

    assert result["total_tokens"] == 45
    assert result["events"] == 1
    assert result["by_module"] == {"resume": {"events": 1, "total_tokens": 45, "estimated_cost_usd": "0.00012"}}
    assert "prompt" not in result
    assert "content" not in result


def test_sensitive_or_unbounded_labels_are_rejected() -> None:
    ledger = _ledger()
    with pytest.raises(UsageValidationError):
        ledger.record("alice", module="user email", provider="openai", model="gpt-test")
    with pytest.raises(UsageValidationError):
        ledger.record("alice", module="chat", provider="openai", model="gpt\nsecret")
    with pytest.raises(UsageValidationError):
        ledger.record("alice", module="chat", provider="openai", model="gpt-test", input_tokens=-1)
