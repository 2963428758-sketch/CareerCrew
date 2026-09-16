"""知识文档治理 API 的 owner/public 边界。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from careercrew_api.auth.dependencies import get_current_user
from careercrew_api.deps import get_runtime_dep
from careercrew_api.main import create_app
from careercrew_api.routers.knowledge_governance import _live_governance_indexer
from careercrew_core.memory.db import FakeMemoryDb


class _Runtime:
    def __init__(self) -> None:
        self.memory_db = FakeMemoryDb()

    def _ensure_stores(self) -> None:
        return None


@pytest.mark.parametrize("fail", [False, True])
def test_cold_governance_edit_initializes_vectors_before_mutation(fail):
    from careercrew_core.knowledge.governance import KnowledgeGovernance

    class Store:
        def delete_by_metadata(self, filters):
            self.deleted = filters
            return 1

        def set_payload_by_filter(self, payload, filters):
            return 1

    class Runtime(_Runtime):
        store = None

        def _ensure_heavy(self):
            if fail:
                raise RuntimeError("secret-provider-error")
            self.store = Store()

    runtime = Runtime()
    service = KnowledgeGovernance(runtime.memory_db)
    created = service.create_document("u1", name="cold", content_sha256="a" * 64,
                                      size_bytes=3, chunks=[{"text": "old"}])
    detail = service.get_document("u1", created["document_id"])
    chunk = detail["versions"][0]["chunks"][0]
    app = create_app()
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "role": "user"}
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            f"/api/knowledge/governance/documents/{created['document_id']}"
            f"/versions/{created['version_id']}/chunks/{chunk['id']}",
            json={"text": "new"},
        )
    assert response.status_code == (503 if fail else 200), response.text
    if fail:
        assert "secret-provider-error" not in response.text
        assert service.get_document("u1", created["document_id"])["versions"][0]["chunks"][0]["text"] == "old"
    else:
        assert runtime.store.deleted["governance_version_id"] == created["version_id"]
        assert "governance_chunk_id" not in runtime.store.deleted


class _Embedding:
    def encode(self, texts):
        return type("Output", (), {"dense": [[0.5, 0.25]], "sparse": [{3: 0.75}]})()


class _VectorStore:
    def __init__(self) -> None:
        self.records = []

    def upsert(self, records) -> None:
        self.records.extend(records)

    def metadata_exists(self, filters) -> bool:
        return any(all(record.metadata.get(k) == v for k, v in filters.items()) for record in self.records)


class _IndexRuntime:
    def __init__(self) -> None:
        self.embedding = None
        self.store = None

    def _ensure_heavy(self) -> None:
        self.embedding = _Embedding()
        self.store = _VectorStore()


def test_live_governance_indexer_writes_tenant_scoped_point_and_verifies_it() -> None:
    runtime = _IndexRuntime()
    indexer = _live_governance_indexer(
        runtime,
        {"id": "doc", "owner_id": "u1", "name": "notes", "category": "knowledge", "visibility": "private"},
        "550e8400-e29b-41d4-a716-446655440010",
        "550e8400-e29b-41d4-a716-446655440011",
        "u1",
    )

    point_id = indexer({"id": "550e8400-e29b-41d4-a716-446655440012", "text": "chunk", "page": 2})

    assert point_id.startswith("governance:550e8400-e29b-41d4-a716-446655440010:")
    record = runtime.store.records[0]
    assert record.metadata["owner_user_id"] == "u1"
    assert record.metadata["record_type"] == "knowledge_governance"
    assert record.metadata["governance_chunk_id"] == "550e8400-e29b-41d4-a716-446655440012"


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


def test_knowledge_governance_api_edits_chunk_and_maps_public_reader_to_forbidden() -> None:
    runtime = _Runtime()
    app = create_app()
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    app.dependency_overrides[get_current_user] = lambda: {"id": "admin", "role": "admin"}

    payload = {
        "name": "Governed notes", "content_sha256": "b" * 64, "size_bytes": 10,
        "category": "knowledge", "visibility": "public",
        "chunks": [{"text": "原始分块", "page": 1}],
    }
    with TestClient(app) as client:
        created = client.post("/api/knowledge/governance/documents", json=payload)
        assert created.status_code == 201, created.text
        body = created.json()
        detail = client.get(f"/api/knowledge/governance/documents/{body['document_id']}")
        chunk_id = detail.json()["versions"][0]["chunks"][0]["id"]
        reindexed = client.post(
            f"/api/knowledge/governance/documents/{body['document_id']}"
            f"/versions/{body['version_id']}/reindex",
        )
        assert reindexed.status_code == 200, reindexed.text
        chunk_updated_at = client.get(
            f"/api/knowledge/governance/documents/{body['document_id']}"
        ).json()["versions"][0]["chunks"][0]["updated_at"]

        app.dependency_overrides[get_current_user] = lambda: {"id": "reader", "role": "user"}
        public_read = client.get(f"/api/knowledge/governance/documents/{body['document_id']}")
        assert public_read.status_code == 200, public_read.text
        public_version = public_read.json()["versions"]
        assert [version["status"] for version in public_version] == ["active"]
        assert all(
            "qdrant_point_id" not in chunk and "text_hash" not in chunk
            for chunk in public_version[0]["chunks"]
        )

        app.dependency_overrides[get_current_user] = lambda: {"id": "admin", "role": "admin"}

        edited = client.patch(
            f"/api/knowledge/governance/documents/{body['document_id']}"
            f"/versions/{body['version_id']}/chunks/{chunk_id}",
            json={"text": "新的分块", "page": 2, "updated_at": chunk_updated_at},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["versions"][0]["chunks"][0]["index_status"] == "pending"
        assert edited.json()["versions"][0]["chunks"][0]["text"] == "新的分块"

        stale = client.patch(
            f"/api/knowledge/governance/documents/{body['document_id']}"
            f"/versions/{body['version_id']}/chunks/{chunk_id}",
            json={"text": "覆盖较新的分块", "page": 2, "updated_at": chunk_updated_at},
        )
        assert stale.status_code == 409, stale.text

        app.dependency_overrides[get_current_user] = lambda: {"id": "reader", "role": "user"}
        forbidden = client.patch(
            f"/api/knowledge/governance/documents/{body['document_id']}"
            f"/versions/{body['version_id']}/chunks/{chunk_id}",
            json={"text": "越权", "page": 2},
        )
        assert forbidden.status_code == 403

    app.dependency_overrides.clear()


def test_knowledge_governance_api_rejects_invalid_chunk_payload() -> None:
    runtime = _Runtime()
    app = create_app()
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "role": "user"}

    payload = {
        "name": "Validation notes", "content_sha256": "c" * 64, "size_bytes": 10,
        "chunks": [{"text": "原始分块", "page": 1}],
    }
    with TestClient(app) as client:
        invalid_document = client.get("/api/knowledge/governance/documents/not-a-uuid")
        assert invalid_document.status_code == 422
        created = client.post("/api/knowledge/governance/documents", json=payload)
        detail = client.get(f"/api/knowledge/governance/documents/{created.json()['document_id']}")
        body = detail.json()
        chunk_id = body["versions"][0]["chunks"][0]["id"]
        invalid = client.patch(
            f"/api/knowledge/governance/documents/{body['id']}"
            f"/versions/{body['versions'][0]['id']}/chunks/{chunk_id}",
            json={"text": "页码错误", "page": 0},
        )
        assert invalid.status_code == 422

    app.dependency_overrides.clear()


def test_knowledge_governance_api_rejects_invalid_expiry_payload() -> None:
    runtime = _Runtime()
    app = create_app()
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "role": "user"}

    payload = {
        "name": "Expiry validation",
        "content_sha256": "d" * 64,
        "size_bytes": 10,
        "expires_at": "not-a-date",
        "chunks": [{"text": "有期限的分块"}],
    }
    with TestClient(app) as client:
        invalid = client.post("/api/knowledge/governance/documents", json=payload)
        assert invalid.status_code == 422, invalid.text

    app.dependency_overrides.clear()


def test_knowledge_governance_api_admin_list_includes_private_documents() -> None:
    runtime = _Runtime()
    app = create_app()
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "role": "user"}

    payload = {
        "name": "私有治理文档", "content_sha256": "f" * 64, "size_bytes": 4,
        "chunks": [{"text": "仅管理员治理"}],
    }
    with TestClient(app) as client:
        created = client.post("/api/knowledge/governance/documents", json=payload)
        assert created.status_code == 201, created.text
        app.dependency_overrides[get_current_user] = lambda: {"id": "admin", "role": "admin"}
        listed = client.get("/api/knowledge/governance/documents")
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["owner_id"] == "u1"

    app.dependency_overrides.clear()
