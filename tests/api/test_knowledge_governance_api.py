"""知识文档治理 API 的 owner/public 边界。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from careercrew_api.auth.dependencies import get_current_user
from careercrew_api.deps import get_runtime_dep
from careercrew_api.main import create_app
from careercrew_core.memory.db import FakeMemoryDb


class _Runtime:
    def __init__(self) -> None:
        self.memory_db = FakeMemoryDb()

    def _ensure_stores(self) -> None:
        return None


def test_knowledge_governance_api_creates_versions_and_rejects_cross_owner_mutation() -> None:
    runtime = _Runtime()
    app = create_app()
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "role": "user"}

    payload = {
        "name": "RAG notes", "content_sha256": "a" * 64, "size_bytes": 10,
        "category": "knowledge", "visibility": "private",
        "chunks": [{"text": "RRF", "page": 1}],
    }
    with TestClient(app) as client:
        created = client.post("/api/knowledge/governance/documents", json=payload)
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["duplicate"] is False

        duplicate = client.post("/api/knowledge/governance/documents", json=payload)
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicate"] is True

        detail = client.get(f"/api/knowledge/governance/documents/{body['document_id']}")
        assert detail.status_code == 200
        assert detail.json()["versions"][0]["chunks"][0]["text"] == "RRF"

        app.dependency_overrides[get_current_user] = lambda: {"id": "u2", "role": "user"}
        forbidden = client.patch(
            f"/api/knowledge/governance/documents/{body['document_id']}",
            json={"credibility": 0.1},
        )
        assert forbidden.status_code == 404

    app.dependency_overrides.clear()
