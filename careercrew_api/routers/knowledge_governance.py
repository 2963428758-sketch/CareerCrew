"""Knowledge document governance endpoints.

The legacy upload/ask routes remain unchanged.  These endpoints expose the
durable document/version/chunk lifecycle with explicit owner/public checks so
the lifecycle can be adopted by the ingestion UI incrementally.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.knowledge.governance import (
    KnowledgeGovernance,
    KnowledgeNotFoundError,
    KnowledgePermissionError,
    KnowledgeValidationError,
)

router = APIRouter()


class KnowledgeChunkRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    page: int | None = Field(default=None, ge=1)


class KnowledgeDocumentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content_sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    category: str = Field(default="knowledge", max_length=100)
    visibility: Literal["private", "public"] = "private"
    mime_type: str = Field(default="application/octet-stream", max_length=255)
    expires_at: str | None = None
    credibility: float = Field(default=1.0, ge=0.0, le=1.0)
    chunks: list[KnowledgeChunkRequest] = Field(default_factory=list, max_length=10_000)


class KnowledgeVersionRequest(BaseModel):
    content_sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    mime_type: str = Field(default="application/octet-stream", max_length=255)
    expires_at: str | None = None
    credibility: float | None = Field(default=None, ge=0.0, le=1.0)
    chunks: list[KnowledgeChunkRequest] = Field(default_factory=list, max_length=10_000)


class KnowledgeDocumentPatch(BaseModel):
    expires_at: str | None = None
    credibility: float | None = Field(default=None, ge=0.0, le=1.0)


class KnowledgeCitationRequest(BaseModel):
    chunk_ids: list[str] = Field(min_length=1, max_length=200)
    request_id: str = Field(min_length=1, max_length=128)


def _service(rt: CareerCrewRuntime) -> KnowledgeGovernance:
    ensure_stores = getattr(rt, "_ensure_stores", None)
    if callable(ensure_stores):
        ensure_stores()
    db = getattr(rt, "knowledge_db", None) or getattr(rt, "memory_db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="知识治理服务暂不可用")
    return KnowledgeGovernance(db)


def _raise(error: Exception) -> None:
    if isinstance(error, KnowledgeNotFoundError):
        raise HTTPException(status_code=404, detail="知识文档不存在或无权访问") from error
    if isinstance(error, KnowledgePermissionError):
        raise HTTPException(status_code=403, detail="无权治理此知识文档") from error
    if isinstance(error, KnowledgeValidationError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


def _admin(current_user: dict[str, str]) -> bool:
    return current_user.get("role") == "admin"


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
        items = _service(rt).list_documents(current_user["id"], include_expired=include_expired)
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


@router.post("/knowledge/governance/documents/{document_id}/versions/{version_id}/reindex")
def reindex_version(
    document_id: str,
    version_id: str,
    current_user: CurrentUser,
    allow_expired: bool = Query(False),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    try:
        return _service(rt).reindex(
            current_user["id"], document_id, version_id,
            allow_expired=allow_expired, is_admin=_admin(current_user),
        )
    except (KnowledgeNotFoundError, KnowledgePermissionError, KnowledgeValidationError) as error:
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
