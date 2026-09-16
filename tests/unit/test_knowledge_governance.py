"""知识文档版本、去重、重索引和引用统计的业务边界。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from careercrew_core.knowledge.governance import (
    KnowledgeConflictError,
    KnowledgeGovernance,
    KnowledgeIndexingError,
    KnowledgeNotFoundError,
    KnowledgePermissionError,
    KnowledgeValidationError,
)
from careercrew_core.memory.db import FakeMemoryDb


def _service() -> tuple[KnowledgeGovernance, FakeMemoryDb]:
    db = FakeMemoryDb()
    return KnowledgeGovernance(db), db


def _create(service: KnowledgeGovernance, owner: str = "u1", **overrides):
    values = {
        "name": "RAG notes",
        "content_sha256": "a" * 64,
        "size_bytes": 10,
        "category": "knowledge",
        "visibility": "private",
        "chunks": [{"text": "RRF 融合", "page": 1}, {"text": "Qdrant", "page": 2}],
    }
    values.update(overrides)
    return service.create_document(owner, is_admin=values["visibility"] == "public", **values)


@pytest.mark.parametrize("initial,target", [("private", "public"), ("public", "private")])
def test_visibility_partial_vector_failure_restores_database_visibility(initial, target):
    class Store:
        visibility = initial
        failed = False

        def set_payload_by_filter(self, payload, filters):
            self.visibility = payload["visibility"]
            if not self.failed:
                self.failed = True
                raise RuntimeError("write applied but response lost")
            return 1

    store = Store()
    service = KnowledgeGovernance(FakeMemoryDb(), vector_store=store)
    created = _create(service, visibility=initial)
    operation = service.publish_document if target == "public" else service.unpublish_document
    with pytest.raises(KnowledgeIndexingError):
        operation("u1", created["document_id"])
    assert service.get_document("u1", created["document_id"])["visibility"] == initial
    assert store.visibility == initial


def test_other_owner_cannot_publish_private_document():
    service, _ = _service()
    created = _create(service)
    with pytest.raises(KnowledgeNotFoundError):
        service.publish_document("u2", created["document_id"])


def test_same_owner_raw_hash_is_duplicate_but_cross_owner_is_not_revealed() -> None:
    service, _ = _service()
    first = _create(service)
    duplicate = _create(service)
    other_owner = _create(service, owner="u2")

    assert first["duplicate"] is False
    assert duplicate["duplicate"] is True
    assert duplicate["document_id"] == first["document_id"]
    assert other_owner["duplicate"] is False
    assert other_owner["document_id"] != first["document_id"]


def test_expiry_must_be_an_iso_date_or_datetime() -> None:
    service, _ = _service()

    with pytest.raises(KnowledgeValidationError, match="expires_at"):
        _create(service, expires_at="not-a-date")


def test_version_is_not_active_until_successful_reindex_and_failure_preserves_active() -> None:
    service, _ = _service()
    first = _create(service)
    service.reindex("u1", first["document_id"], first["version_id"])
    detail = service.get_document("u1", first["document_id"])
    assert detail["active_version_id"] == first["version_id"]

    newer = service.create_version(
        "u1", first["document_id"], content_sha256="b" * 64, size_bytes=12,
        chunks=[{"text": "新的 RAG 内容", "page": 1}],
    )
    assert service.get_document("u1", first["document_id"])["active_version_id"] == first["version_id"]

    def broken(_chunk):
        raise RuntimeError("index failed")

    with pytest.raises(RuntimeError):
        service.reindex("u1", first["document_id"], newer["version_id"], indexer=broken)
    failed = service.get_document("u1", first["document_id"])
    assert failed["active_version_id"] == first["version_id"]
    assert next(v for v in failed["versions"] if v["id"] == newer["version_id"])["status"] == "failed"

    service.reindex("u1", first["document_id"], newer["version_id"])
    switched = service.get_document("u1", first["document_id"])
    assert switched["active_version_id"] == newer["version_id"]
    assert next(v for v in switched["versions"] if v["id"] == first["version_id"])["status"] == "archived"


def test_stale_indexing_versions_are_recovered_and_not_left_permanently_indexing() -> None:
    service, db = _service()
    created = _create(service)
    state = db._knowledge_governance
    version = state["versions"][created["version_id"]]
    stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    version["status"] = "indexing"
    version["updated_at"] = stale

    result = service.recover_stale_indexing("u1", stale_after_seconds=60)

    assert result == {"recovered": 1, "failed": 1, "activated": 0}
    assert version["status"] == "failed"
    assert all(chunk["index_status"] == "failed" for chunk in state["chunks"].values())


def test_reindex_failure_of_current_active_version_preserves_public_projection() -> None:
    service, _ = _service()
    created = _create(service, visibility="public")
    service.reindex("u1", created["document_id"], created["version_id"])
    before = service.get_document("u1", created["document_id"])
    before_version = before["versions"][0]
    before_chunk = before_version["chunks"][0]

    def broken(_chunk):
        raise RuntimeError("qdrant unavailable")

    with pytest.raises(RuntimeError):
        service.reindex(
            "u1", created["document_id"], created["version_id"], indexer=broken,
        )

    after = service.get_document("u1", created["document_id"])
    assert after["active_version_id"] == created["version_id"]
    version = after["versions"][0]
    assert version["status"] == "active"
    assert version["indexed_at"] == before_version["indexed_at"]
    assert version["chunks"][0]["index_status"] == "indexed"
    assert version["chunks"][0]["qdrant_point_id"] == before_chunk["qdrant_point_id"]
    public = service.get_document("u2", created["document_id"])
    assert public["active_version_id"] == created["version_id"]


def test_active_version_expiry_is_hidden_from_public_reader() -> None:
    service, _ = _service()
    document = _create(service, visibility="public")
    expired = service.create_version(
        "u1", document["document_id"], content_sha256="d" * 64, size_bytes=5,
        expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        chunks=[{"text": "过期版本"}],
    )
    service.reindex(
        "u1", document["document_id"], expired["version_id"], allow_expired=True,
    )

    with pytest.raises(KnowledgeNotFoundError):
        service.get_document("u2", document["document_id"])


def test_chunk_edit_requires_current_updated_at_when_supplied() -> None:
    service, _ = _service()
    created = _create(service)
    detail = service.get_document("u1", created["document_id"])
    chunk = detail["versions"][0]["chunks"][0]
    expected_updated_at = chunk["updated_at"]

    service.update_chunk(
        "u1", created["document_id"], created["version_id"], chunk["id"],
        text="第一次编辑", page=1, expected_updated_at=expected_updated_at,
    )
    with pytest.raises(KnowledgeConflictError):
        service.update_chunk(
            "u1", created["document_id"], created["version_id"], chunk["id"],
            text="覆盖较新的编辑", page=1, expected_updated_at=expected_updated_at,
        )


def test_admin_can_list_other_users_private_governed_documents() -> None:
    service, _ = _service()
    created = _create(service, owner="u1")

    assert service.list_documents("u2") == []
    admin_items = service.list_documents("admin", is_admin=True)
    assert [item["id"] for item in admin_items] == [created["document_id"]]


def test_expiry_credibility_chunks_and_citations_are_visible_only_in_owner_scope() -> None:
    service, _ = _service()
    expired = _create(
        service,
        expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        credibility=0.4,
    )
    assert service.list_documents("u1") == []
    detail = service.get_document("u1", expired["document_id"])
    assert detail["credibility"] == 0.4
    assert len(detail["versions"][0]["chunks"]) == 2

    service.reindex("u1", expired["document_id"], expired["version_id"], allow_expired=True)
    chunk_id = detail["versions"][0]["chunks"][0]["id"]
    first = service.record_citations(
        "u1", expired["document_id"], expired["version_id"], [chunk_id], request_id="req-1",
    )
    again = service.record_citations(
        "u1", expired["document_id"], expired["version_id"], [chunk_id], request_id="req-1",
    )
    assert first == again == {chunk_id: 1}
    assert service.get_document("u1", expired["document_id"])["citation_hits"] == 1
    with pytest.raises(KnowledgeNotFoundError):
        service.get_document("u2", expired["document_id"])


def test_public_document_can_be_read_but_only_owner_or_admin_can_govern() -> None:
    service, _ = _service()
    with pytest.raises(KnowledgePermissionError):
        service.create_document(
            "u1", name="未经审核", content_sha256="f" * 64, size_bytes=1,
            visibility="public", chunks=[{"text": "不应发布"}],
        )
    public = _create(service, visibility="public")
    service.reindex("u1", public["document_id"], public["version_id"])
    assert service.get_document("u2", public["document_id"])["name"] == "RAG notes"
    public_detail = service.get_document("u2", public["document_id"])
    assert [version["status"] for version in public_detail["versions"]] == ["active"]
    assert all(
        "qdrant_point_id" not in chunk and "text_hash" not in chunk
        for chunk in public_detail["versions"][0]["chunks"]
    )
    newer = service.create_version(
        "u1", public["document_id"], content_sha256="e" * 64, size_bytes=2,
        chunks=[{"text": "尚未发布的私密草稿"}],
    )
    assert newer["version_id"] != public["version_id"]
    assert "尚未发布的私密草稿" not in str(service.get_document("u2", public["document_id"]))
    with pytest.raises(KnowledgePermissionError):
        service.update_document("u2", public["document_id"], credibility=0.1)
    with pytest.raises(KnowledgePermissionError):
        service.reindex("u2", public["document_id"], public["version_id"])
    service.update_document("admin", public["document_id"], credibility=0.9, is_admin=True)
    assert service.get_document("u2", public["document_id"])["credibility"] == 0.9


def test_chunk_edit_invalidates_active_index_until_explicit_reindex() -> None:
    service, _ = _service()
    created = _create(service)
    service.reindex("u1", created["document_id"], created["version_id"])
    before = service.get_document("u1", created["document_id"])
    chunk_id = before["versions"][0]["chunks"][0]["id"]
    original_hash = before["versions"][0]["content_sha256"]
    original_size = before["versions"][0]["size_bytes"]
    original_source_hash = before["versions"][0]["source_content_sha256"]
    original_source_size = before["versions"][0]["source_size_bytes"]

    edited = service.update_chunk(
        "u1", created["document_id"], created["version_id"], chunk_id,
        text="编辑后的 RRF 说明", page=3,
    )

    assert edited["active_version_id"] is None
    version = edited["versions"][0]
    assert version["status"] == "draft"
    assert version["indexed_at"] is None
    assert version["content_sha256"] != original_hash
    assert version["size_bytes"] != original_size
    assert version["source_content_sha256"] == original_source_hash
    assert version["source_size_bytes"] == original_source_size
    chunk = version["chunks"][0]
    assert chunk["text"] == "编辑后的 RRF 说明"
    assert chunk["page"] == 3
    assert chunk["index_status"] == "pending"
    assert chunk["qdrant_point_id"] is None

    reindexed = service.reindex("u1", created["document_id"], created["version_id"])
    assert reindexed["active_version_id"] == created["version_id"]
    assert reindexed["versions"][0]["status"] == "active"


def test_governance_vector_projection_retires_old_version_and_activates_new_one() -> None:
    class Store:
        def __init__(self) -> None:
            self.status_updates: list[tuple[dict, dict]] = []
            self.deleted: list[dict] = []
            self.points: set[tuple[str, str]] = set()

        def set_payload_by_filter(self, payload, filters):
            self.status_updates.append((dict(payload), dict(filters)))
            version_id = filters.get("governance_version_id")
            if version_id:
                self.points.add((str(filters["governance_document_id"]), str(version_id)))
            return 100

        def delete_by_metadata(self, filters):
            self.deleted.append(dict(filters))
            return 1

    store = Store()
    service = KnowledgeGovernance(FakeMemoryDb(), vector_store=store)
    first = _create(service)
    service.reindex(
        "u1", first["document_id"], first["version_id"],
        indexer=lambda chunk: f"p-{chunk['id']}",
    )
    newer = service.create_version(
        "u1", first["document_id"], content_sha256="b" * 64, size_bytes=12,
        chunks=[{"text": "新的治理内容", "page": 1}],
    )

    service.reindex(
        "u1", first["document_id"], newer["version_id"],
        indexer=lambda chunk: f"p-{chunk['id']}",
    )

    assert any(
        payload == {"governance_status": "active"}
        and filters["governance_version_id"] == newer["version_id"]
        for payload, filters in store.status_updates
    )
    assert {
        "record_type": "knowledge_governance",
        "governance_document_id": first["document_id"],
        "governance_version_id": first["version_id"],
    } in store.deleted


def test_chunk_edit_removes_old_governance_vector_before_db_invalidation() -> None:
    class Store:
        def __init__(self) -> None:
            self.deleted = []

        def delete_by_metadata(self, filters):
            self.deleted.append(dict(filters))
            return 1

    store = Store()
    service = KnowledgeGovernance(FakeMemoryDb(), vector_store=store)
    created = _create(service)
    detail = service.get_document("u1", created["document_id"])
    chunk_id = detail["versions"][0]["chunks"][0]["id"]

    from careercrew_core.knowledge.governance import KnowledgeConflictError

    with pytest.raises(KnowledgeConflictError):
        service.update_chunk(
            "u1", created["document_id"], created["version_id"], chunk_id,
            text="stale edit", page=1, expected_updated_at="2000-01-01T00:00:00Z",
        )
    assert store.deleted == [], "Rejected edits must preserve the existing vector"

    service.update_chunk(
        "u1", created["document_id"], created["version_id"], chunk_id,
        text="重新编辑", page=1,
    )

    assert store.deleted == [{
        "record_type": "knowledge_governance",
        "governance_document_id": created["document_id"],
        "governance_version_id": created["version_id"],
    }]


def test_empty_version_cannot_be_activated_by_reindex() -> None:
    service, _ = _service()
    created = _create(service, chunks=[])

    with pytest.raises(KnowledgeValidationError, match="至少需要一个有效分块"):
        service.reindex("u1", created["document_id"], created["version_id"])


def test_chunk_edit_enforces_governance_scope_and_payload_validation() -> None:
    service, _ = _service()
    public = _create(service, visibility="public")
    chunk_id = service.get_document("u1", public["document_id"])["versions"][0]["chunks"][0]["id"]

    with pytest.raises(KnowledgePermissionError):
        service.update_chunk(
            "u2", public["document_id"], public["version_id"], chunk_id,
            text="越权修改", page=1,
        )
    with pytest.raises(KnowledgeNotFoundError):
        service.update_chunk(
            "u1", public["document_id"], str(uuid.uuid4()), chunk_id,
            text="版本不匹配", page=1,
        )
    with pytest.raises(KnowledgeValidationError):
        service.update_chunk(
            "u1", public["document_id"], public["version_id"], chunk_id,
            text="", page=1,
        )
    with pytest.raises(KnowledgeValidationError):
        service.update_chunk(
            "u1", public["document_id"], public["version_id"], chunk_id,
            text="页码不合法", page=0,
        )


def test_invalid_sha_and_chunk_payloads_are_rejected() -> None:
    service, _ = _service()
    with pytest.raises(KnowledgeValidationError):
        _create(service, content_sha256="not-a-sha")
    with pytest.raises(KnowledgeValidationError):
        _create(service, chunks=[{"text": ""}])
