"""预算原子预留、软阈值降级提示和并发边界。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.usage.ledger import (
    BudgetExceeded,
    UsageLedger,
)


def test_budget_reservation_and_release_use_actual_consumption() -> None:
    ledger = UsageLedger(FakeMemoryDb())
    ledger.set_budget("alice", period="daily", token_limit=100)

    reservation = ledger.reserve("alice", module="chat", provider="x", model="unknown", estimated_tokens=60)
    assert reservation is not None
    with pytest.raises(BudgetExceeded) as exc:
        ledger.reserve("alice", module="chat", provider="x", model="unknown", estimated_tokens=41)
    assert exc.value.reason == "token_budget"

    ledger.record(
        "alice", module="chat", provider="x", model="unknown",
        input_tokens=20, output_tokens=25, reservation_id=reservation["reservation_id"],
    )
    summary = ledger.summary("alice")
    assert summary["total_tokens"] == 45
    assert summary["reserved_tokens"] == 0


def test_cost_budget_with_unknown_price_fails_closed() -> None:
    ledger = UsageLedger(FakeMemoryDb())
    ledger.set_budget("alice", period="monthly", cost_limit_usd="1.00")

    with pytest.raises(BudgetExceeded) as exc:
        ledger.reserve("alice", module="chat", provider="x", model="not-priced", estimated_tokens=10)
    assert exc.value.reason == "unknown_pricing"


def test_soft_budget_returns_explicit_downgrade_recommendation() -> None:
    ledger = UsageLedger(FakeMemoryDb())
    ledger.set_budget(
        "alice", period="daily", token_limit=100, soft_limit_ratio=0.8,
        downgrade_model="cheap-model",
    )

    result = ledger.reserve("alice", module="chat", provider="x", model="large-model", estimated_tokens=85)

    assert result["recommended_model"] == "cheap-model"
    assert result["downgrade_reason"] == "budget_soft_limit"


def test_concurrent_reservations_cannot_cross_hard_limit() -> None:
    ledger = UsageLedger(FakeMemoryDb())
    ledger.set_budget("alice", period="daily", token_limit=100)

    def reserve_one(index: int):
        try:
            return ledger.reserve(
                "alice", module="chat", provider="x", model="unknown",
                estimated_tokens=40, source_request_id=f"req-{index}",
            )
        except BudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve_one, range(8)))

    assert len([item for item in results if item is not None]) == 2
    assert ledger.summary("alice")["reserved_tokens"] == 80


def test_module_budget_is_narrower_than_user_budget() -> None:
    ledger = UsageLedger(FakeMemoryDb())
    ledger.set_budget("alice", period="daily", token_limit=500)
    ledger.set_budget("alice", scope_type="module", scope_key="resume", period="daily", token_limit=50)

    ledger.reserve("alice", module="resume", provider="x", model="unknown", estimated_tokens=40)
    with pytest.raises(BudgetExceeded) as exc:
        ledger.reserve("alice", module="resume", provider="x", model="unknown", estimated_tokens=11)
    assert exc.value.scope_key == "resume"
