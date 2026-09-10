"""知识文档版本、去重、重索引和引用统计的业务边界。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from careercrew_core.knowledge.governance import (
    KnowledgeGovernance,
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
    return service.create_document(owner, **values)


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
    public = _create(service, visibility="public")
    assert service.get_document("u2", public["document_id"])["name"] == "RAG notes"
    with pytest.raises(KnowledgePermissionError):
        service.update_document("u2", public["document_id"], credibility=0.1)
    with pytest.raises(KnowledgePermissionError):
        service.reindex("u2", public["document_id"], public["version_id"])
    service.update_document("admin", public["document_id"], credibility=0.9, is_admin=True)
    assert service.get_document("u2", public["document_id"])["credibility"] == 0.9


def test_invalid_sha_and_chunk_payloads_are_rejected() -> None:
    service, _ = _service()
    with pytest.raises(KnowledgeValidationError):
        _create(service, content_sha256="not-a-sha")
    with pytest.raises(KnowledgeValidationError):
        _create(service, chunks=[{"text": ""}])
