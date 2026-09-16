"""Knowledge document governance endpoints.

The legacy upload/ask routes remain unchanged.  These endpoints expose the
durable document/version/chunk lifecycle with explicit owner/public checks so
the lifecycle can be adopted by the ingestion UI incrementally.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.knowledge.governance import (
    KnowledgeConflictError,
    KnowledgeGovernance,
    KnowledgeIndexingError,
    KnowledgeNotFoundError,
    KnowledgePermissionError,
    KnowledgeValidationError,
)

router = APIRouter()


class KnowledgeChunkRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    page: int | None = Field(default=None, ge=1)


class KnowledgeChunkPatch(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    page: int | None = Field(default=None, ge=1)
    updated_at: str | None = Field(default=None, max_length=80)


class KnowledgeDocumentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content_sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    category: str = Field(default="knowledge", max_length=100)
    visibility: Literal["private", "public"] = "private"
    mime_type: str = Field(default="application/octet-stream", max_length=255)
    expires_at: datetime | date | None = None
    credibility: float = Field(default=1.0, ge=0.0, le=1.0)
    chunks: list[KnowledgeChunkRequest] = Field(default_factory=list, max_length=10_000)


class KnowledgeVersionRequest(BaseModel):
    content_sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    mime_type: str = Field(default="application/octet-stream", max_length=255)
    expires_at: datetime | date | None = None
    credibility: float | None = Field(default=None, ge=0.0, le=1.0)
    chunks: list[KnowledgeChunkRequest] = Field(default_factory=list, max_length=10_000)


class KnowledgeDocumentPatch(BaseModel):
    expires_at: datetime | date | None = None
    credibility: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeCitationRequest(BaseModel):
    chunk_ids: list[str] = Field(min_length=1, max_length=200)
    request_id: str = Field(min_length=1, max_length=128)


def _service(rt: CareerCrewRuntime) -> KnowledgeGovernance:
    ensure_stores = getattr(rt, "_ensure_stores", None)
    if callable(ensure_stores):
        ensure_stores()
    db = getattr(rt, "knowledge_db", None) or getattr(rt, "memory_db", None)
    ensure_heavy = getattr(rt, "_ensure_heavy", None)
    if getattr(rt, "store", None) is None and callable(ensure_heavy):
        try:
            ensure_heavy()
            if getattr(rt, "store", None) is None and not KnowledgeGovernance(db)._fake:
                raise RuntimeError("vector backend unavailable")
        except Exception as exc:
            raise HTTPException(status_code=503, detail="知识向量服务暂不可用") from exc
    if db is None:
        raise HTTPException(status_code=503, detail="知识治理服务暂不可用")
    return KnowledgeGovernance(db, vector_store=getattr(rt, "store", None))


def _raise(error: Exception) -> None:
    if isinstance(error, KnowledgeConflictError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, KnowledgeIndexingError):
        raise HTTPException(status_code=503, detail=str(error)) from error
    if isinstance(error, KnowledgeNotFoundError):
        raise HTTPException(status_code=404, detail="知识文档不存在或无权访问") from error
    if isinstance(error, KnowledgePermissionError):
        raise HTTPException(status_code=403, detail="无权治理此知识文档") from error
    if isinstance(error, KnowledgeValidationError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


def _admin(current_user: dict[str, str]) -> bool:
    return current_user.get("role") == "admin"


def _live_governance_indexer(
    rt: CareerCrewRuntime,
    document: dict[str, Any],
    document_id: str,
    version_id: str,
    owner_id: str,
):
    """Build a real embedding/Qdrant indexer for PostgreSQL governance rows.

    The relational service deliberately does not import the runtime's heavy AI
    stack.  This adapter is the boundary that turns each governed chunk into
    a tenant-scoped, idempotent vector point and verifies the write before the
    version can become active.
    """

    def index(chunk: dict[str, Any]) -> str:
        try:
            ensure_heavy = getattr(rt, "_ensure_heavy", None)
            if not callable(ensure_heavy):
                raise RuntimeError("重组件初始化接口不可用")
            ensure_heavy()
            embedding = getattr(rt, "embedding", None)
            store = getattr(rt, "store", None)
            if embedding is None or store is None:
                raise RuntimeError("embedding 或 Qdrant store 未初始化")

            text = str(chunk.get("text") or "")
            output = embedding.encode([text])
            dense = getattr(output, "dense", None)
            if dense is None or len(dense) != 1:
                raise RuntimeError("embedding 返回的 dense 数量不匹配")
            sparse = getattr(output, "sparse", None)
            point_id = f"governance:{document_id}:{version_id}:{chunk['id']}"
            from careercrew_ai.vector_store.base_vector_store import VectorRecord

            metadata = {
                "doc": f"governance:{document_id}",
                "doc_name": str(document.get("name") or ""),
                "title": str(document.get("name") or ""),
                "source": str(document.get("name") or ""),
                "category": str(document.get("category") or "knowledge"),
                "owner_user_id": str(document.get("owner_id") or owner_id),
                "visibility": str(document.get("visibility") or "private"),
                "record_type": "knowledge_governance",
                # A point is staged first.  KnowledgeGovernance flips the
                # whole version to active only after the relational cutover.
                "governance_status": "indexing",
                "governance_document_id": document_id,
                "governance_version_id": version_id,
                "governance_chunk_id": str(chunk["id"]),
            }
            if chunk.get("page") is not None:
                metadata["page"] = int(chunk["page"])
            store.upsert([VectorRecord(
                id=point_id,
                dense=dense[0],
                sparse=sparse[0] if sparse else None,
                text=text,
                metadata=metadata,
            )])
            metadata_exists = getattr(store, "metadata_exists", None)
            if not callable(metadata_exists) or not metadata_exists({
                "governance_document_id": document_id,
                "governance_version_id": version_id,
                "governance_chunk_id": str(chunk["id"]),
                "owner_user_id": metadata["owner_user_id"],
            }):
                raise RuntimeError("Qdrant 写入后校验未命中")
            return point_id
        except KnowledgeIndexingError:
            raise
        except Exception as error:
            # Provider errors may contain API keys, URLs or request bodies.
            # Keep the cause for logs/debugging but never expose it in HTTP.
            raise KnowledgeIndexingError("知识分块索引失败，请稍后重试") from error

    return index


@router.post("/knowledge/governance/documents", status_code=status.HTTP_201_CREATED)
def create_document(
    request: KnowledgeDocumentRequest,
    response: Response,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    if request.visibility == "public" and not _admin(current_user):
        raise HTTPException(status_code=403, detail="只有管理员可以创建公共知识文档")
    try:
        result = _service(rt).create_document(
            current_user["id"], name=request.name, content_sha256=request.content_sha256,
            size_bytes=request.size_bytes, category=request.category,
            visibility=request.visibility, mime_type=request.mime_type,
            expires_at=request.expires_at, credibility=request.credibility,
            chunks=[chunk.model_dump() for chunk in request.chunks],
            is_admin=_admin(current_user),
        )
    except (KnowledgeNotFoundError, KnowledgePermissionError, KnowledgeValidationError) as error:
        _raise(error)
    if result.get("duplicate"):
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/knowledge/governance/documents")
def list_documents(
    current_user: CurrentUser,
    include_expired: bool = Query(False),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    try:
        items = _service(rt).list_documents(
            current_user["id"], include_expired=include_expired,
            is_admin=_admin(current_user),
        )
    except (KnowledgeNotFoundError, KnowledgePermissionError, KnowledgeValidationError) as error:
        _raise(error)
    return {"items": items, "total": len(items)}


@router.get("/knowledge/governance/documents/{document_id}")
def get_document(
    document_id: str,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    try:
        return _service(rt).get_document(
            current_user["id"], document_id, is_admin=_admin(current_user),
        )
    except (KnowledgeNotFoundError, KnowledgePermissionError, KnowledgeValidationError) as error:
        _raise(error)
    return {}  # pragma: no cover - _raise always raises


@router.post("/knowledge/governance/documents/{document_id}/versions")
def create_version(
    document_id: str,
    request: KnowledgeVersionRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    try:
        return _service(rt).create_version(
            current_user["id"], document_id, content_sha256=request.content_sha256,
            size_bytes=request.size_bytes, mime_type=request.mime_type,
            expires_at=request.expires_at, credibility=request.credibility,
            chunks=[chunk.model_dump() for chunk in request.chunks],
            is_admin=_admin(current_user),
        )
    except (KnowledgeNotFoundError, KnowledgePermissionError, KnowledgeValidationError) as error:
        _raise(error)
    return {}  # pragma: no cover - _raise always raises


@router.patch("/knowledge/governance/documents/{document_id}")
def update_document(
    document_id: str,
    request: KnowledgeDocumentPatch,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    try:
        return _service(rt).update_document(
            current_user["id"], document_id, expires_at=request.expires_at,
            credibility=request.credibility, is_admin=_admin(current_user),
        )
    except (KnowledgeNotFoundError, KnowledgePermissionError, KnowledgeValidationError) as error:
        _raise(error)
    return {}  # pragma: no cover - _raise always raises


@router.patch("/knowledge/governance/documents/{document_id}/versions/{version_id}/chunks/{chunk_id}")
def update_chunk(
    document_id: str,
    version_id: str,
    chunk_id: str,
    request: KnowledgeChunkPatch,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    try:
        return _service(rt).update_chunk(
            current_user["id"], document_id, version_id, chunk_id,
            text=request.text, page=request.page,
            expected_updated_at=request.updated_at, is_admin=_admin(current_user),
        )
    except (
        KnowledgeNotFoundError, KnowledgePermissionError, KnowledgeValidationError,
        KnowledgeConflictError,
    ) as error:
        _raise(error)
    return {}  # pragma: no cover - _raise always raises


@router.post("/knowledge/governance/documents/{document_id}/versions/{version_id}/reindex")
def reindex_version(
    document_id: str,
    version_id: str,
    current_user: CurrentUser,
    allow_expired: bool = Query(False),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    try:
        governance = _service(rt)
        indexer = None
        if not governance._fake:
            document = governance.get_document(
                current_user["id"], document_id, is_admin=_admin(current_user),
            )
            indexer = _live_governance_indexer(
                rt, document, document_id, version_id, current_user["id"],
            )
            governance.vector_store = getattr(rt, "store", None)
        return governance.reindex(
            current_user["id"], document_id, version_id,
            indexer=indexer, allow_expired=allow_expired,
            is_admin=_admin(current_user),
        )
    except (
        KnowledgeNotFoundError, KnowledgePermissionError, KnowledgeValidationError,
        KnowledgeConflictError, KnowledgeIndexingError,
    ) as error:
        _raise(error)
    return {}  # pragma: no cover - _raise always raises


@router.post("/knowledge/governance/documents/{document_id}/versions/{version_id}/citations")
def record_citations(
    document_id: str,
    version_id: str,
    request: KnowledgeCitationRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    try:
        counts = _service(rt).record_citations(
            current_user["id"], document_id, version_id, request.chunk_ids,
            request_id=request.request_id,
        )
    except (KnowledgeNotFoundError, KnowledgePermissionError, KnowledgeValidationError) as error:
        _raise(error)
    return {"counts": counts}


__all__ = ["router"]
