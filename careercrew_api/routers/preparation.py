"""Job preparation API, usable without initializing any LLM runtime."""
import os
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_core.preparation.exports import export_docx, export_pdf
from careercrew_core.preparation.models import (
    Opportunity,
    OpportunityInput,
    PreparationSession,
    PreparationSessionInput,
    ResumeVersion,
    ResumeVersionInput,
)
from careercrew_core.preparation.store import PreparationStore

router = APIRouter()


@lru_cache(maxsize=1)
def get_preparation_store() -> PreparationStore:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise HTTPException(status_code=503, detail="岗位准备存储尚未配置")
    return PreparationStore(dsn)


Store = Annotated[PreparationStore, Depends(get_preparation_store)]


def _found(value):
    if value is None:
        raise HTTPException(status_code=404, detail="岗位、简历版本或准备会话不存在")
    return value


@router.get("/opportunities", response_model=list[Opportunity])
def list_opportunities(user: CurrentUser, store: Store):
    return store.list_opportunities(user["id"])


@router.post("/opportunities", response_model=Opportunity, status_code=201)
def create_opportunity(payload: OpportunityInput, user: CurrentUser, store: Store):
    return store.create_opportunity(user["id"], payload.model_dump())


@router.get("/opportunities/{opportunity_id}", response_model=Opportunity)
def get_opportunity(opportunity_id: str, user: CurrentUser, store: Store):
    return _found(store.get_opportunity(user["id"], opportunity_id))


@router.put("/opportunities/{opportunity_id}", response_model=Opportunity)
def update_opportunity(opportunity_id: str, payload: OpportunityInput, user: CurrentUser, store: Store):
    return _found(store.update_opportunity(user["id"], opportunity_id, payload.model_dump()))


@router.delete("/opportunities/{opportunity_id}")
def delete_opportunity(opportunity_id: str, user: CurrentUser, store: Store):
    if not store.delete_opportunity(user["id"], opportunity_id):
        _found(None)
    return {"ok": True}


@router.get("/opportunities/{opportunity_id}/versions", response_model=list[ResumeVersion])
def list_versions(opportunity_id: str, user: CurrentUser, store: Store):
    _found(store.get_opportunity(user["id"], opportunity_id))
    return store.list_versions(user["id"], opportunity_id)


@router.post("/opportunities/{opportunity_id}/versions", response_model=ResumeVersion, status_code=201)
def create_version(opportunity_id: str, payload: ResumeVersionInput, user: CurrentUser, store: Store):
    return _found(store.create_version(user["id"], opportunity_id, payload.model_dump()))


@router.get("/opportunities/{opportunity_id}/versions/{version_id}/export")
def export_version(opportunity_id: str, version_id: str, user: CurrentUser, store: Store,
                   format: Literal["pdf", "docx"] = "pdf"):
    version = _found(store.get_version(user["id"], opportunity_id, version_id))
    if format == "pdf":
        body = export_pdf(version["label"], version["content"])
        mime = "application/pdf"
    else:
        body = export_docx(version["label"], version["content"])
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    name = "".join(c for c in version["label"] if c not in '/\\:*?"<>|' and ord(c) >= 32)
    name = (name.strip(" .") or "简历") + "." + format
    return Response(body, media_type=mime, headers={
        "Content-Disposition": f"attachment; filename=resume.{format}; filename*=UTF-8''{quote(name, safe='')}",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/opportunities/{opportunity_id}/sessions", response_model=PreparationSession, status_code=201)
def create_session(opportunity_id: str, payload: PreparationSessionInput, user: CurrentUser, store: Store):
    return _found(store.create_session(user["id"], opportunity_id, payload.model_dump()))


@router.get("/sessions/{thread_id}", response_model=PreparationSession)
def get_session(thread_id: str, user: CurrentUser, store: Store):
    return _found(store.get_session(user["id"], thread_id))
