"""长期记忆治理 API 的租户和状态边界。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from careercrew_api.auth.dependencies import get_current_user
from careercrew_api.deps import get_runtime_dep
from careercrew_api.main import create_app
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.records import BackfillItem, LongTermMemoryRepository


class _Runtime:
    def __init__(self, db: FakeMemoryDb) -> None:
        self.memory_db = db

    def _ensure_stores(self) -> None:
        return None

    def memory_records(self, user_id: str, **kwargs):
        from careercrew_core.memory.governance import MemoryGovernance

        rows = MemoryGovernance(self.memory_db).list_records(
            user_id, status="active", category=kwargs.get("category", ""),
            query=kwargs.get("query", ""), limit=kwargs.get("limit", 20),
        )
        return {"items": rows, "next_cursor": None, "total": len(rows)}


def _seed(db: FakeMemoryDb) -> dict:
    row, _ = LongTermMemoryRepository(db).upsert(BackfillItem(
        user_id="u1", memory_type="semantic", category="profile",
        normalized_key="semantic:profile.direction", display_text="Java",
        payload={"value": "Java"}, source_type="test", legacy_id="legacy-1",
    ))
    return row


def test_memory_governance_api_enforces_owner_and_row_version() -> None:
    db = FakeMemoryDb()
    row = _seed(db)
    app = create_app()
    runtime = _Runtime(db)
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "role": "user"}

    with TestClient(app) as client:
        response = client.patch(
            f"/api/memory/records/{row['id']}",
            json={"action": "confirm", "row_version": 1, "reason": "确认"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["record"]["row_version"] == 2

        stale = client.patch(
            f"/api/memory/records/{row['id']}",
            json={"action": "expire", "row_version": 1, "reason": "过期"},
        )
        assert stale.status_code == 409

        app.dependency_overrides[get_current_user] = lambda: {"id": "u2", "role": "user"}
        forbidden = client.get(f"/api/memory/records/{row['id']}/history")
        assert forbidden.status_code == 404

    app.dependency_overrides.clear()


def test_memory_records_status_all_exposes_owned_non_active_history() -> None:
    db = FakeMemoryDb()
    row = _seed(db)
    app = create_app()
    runtime = _Runtime(db)
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "role": "user"}

    with TestClient(app) as client:
        assert client.patch(
            f"/api/memory/records/{row['id']}",
            json={"action": "ignore", "row_version": 1, "reason": "稍后确认"},
        ).status_code == 200
        assert client.get("/api/memory/records").json()["items"] == []
        all_rows = client.get("/api/memory/records", params={"status": "all"})
        assert all_rows.status_code == 200, all_rows.text
        assert all_rows.json()["items"][0]["status"] == "ignored"

    app.dependency_overrides.clear()
