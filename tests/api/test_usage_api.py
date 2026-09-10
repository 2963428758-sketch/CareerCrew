"""用量 API 的 owner/admin 边界。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from careercrew_api.auth.dependencies import get_current_user
from careercrew_api.deps import get_runtime_dep
from careercrew_api.main import create_app
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.usage.ledger import UsageLedger


class _Runtime:
    def __init__(self) -> None:
        self.memory_db = FakeMemoryDb()

    def _ensure_stores(self) -> None:
        return None


def test_usage_api_exposes_owner_summary_and_admin_budget_policy() -> None:
    runtime = _Runtime()
    UsageLedger(runtime.memory_db).record(
        "u1", module="chat", provider="x", model="m", input_tokens=10, output_tokens=5,
    )
    app = create_app()
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "role": "user"}

    with TestClient(app) as client:
        summary = client.get("/api/usage/summary")
        assert summary.status_code == 200, summary.text
        assert summary.json()["total_tokens"] == 15

        forbidden = client.put(
            "/api/usage/budgets/u1",
            json={"period": "daily", "token_limit": 100},
        )
        assert forbidden.status_code == 403

        app.dependency_overrides[get_current_user] = lambda: {"id": "admin", "role": "admin"}
        saved = client.put(
            "/api/usage/budgets/u1",
            json={"period": "daily", "token_limit": 100, "downgrade_model": "cheap"},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["token_limit"] == 100

    app.dependency_overrides.clear()
