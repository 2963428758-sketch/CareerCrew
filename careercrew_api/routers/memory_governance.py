"""User-facing long-term memory correction endpoints."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.memory.governance import (
    MemoryConflictError,
    MemoryGovernance,
    MemoryNotFoundError,
    MemoryValidationError,
)

router = APIRouter()


class MemoryActionRequest(BaseModel):
    action: Literal["confirm", "edit", "ignore", "expire"]
    row_version: int = Field(ge=1)
    display_text: str | None = Field(default=None, max_length=20_000)
    value: Any = None
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_edit_payload(self):
        if self.action == "edit" and not (self.display_text or "").strip():
            raise ValueError("edit 操作必须提供 display_text")
        return self


class MemoryMergeRequest(BaseModel):
    other_memory_id: str = Field(min_length=1, max_length=100)
    row_version: int = Field(ge=1)
    other_row_version: int = Field(ge=1)
    reason: str = Field(default="", max_length=500)


def _service(rt: CareerCrewRuntime) -> MemoryGovernance:
    ensure_stores = getattr(rt, "_ensure_stores", None)
    if callable(ensure_stores):
        ensure_stores()
    db = getattr(rt, "memory_db", None)
    if db is None:
        memory_service = getattr(rt, "memory_service", None)
        db = getattr(memory_service, "_db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="记忆服务暂不可用")
    return MemoryGovernance(db)


def _raise(error: Exception) -> None:
    if isinstance(error, MemoryNotFoundError):
        raise HTTPException(status_code=404, detail="记忆不存在或无权访问") from error
    if isinstance(error, MemoryConflictError):
        raise HTTPException(status_code=409, detail="记忆已更新，请刷新后重试") from error
    if isinstance(error, MemoryValidationError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


@router.patch("/memory/records/{memory_id}")
def update_memory_record(
    memory_id: str,
    request: MemoryActionRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    service = _service(rt)
    try:
        record = service.apply_action(
            current_user["id"], memory_id, action=request.action,
            expected_row_version=request.row_version, display_text=request.display_text,
            value=request.value, reason=request.reason, actor_id=current_user["id"],
        )
    except (MemoryNotFoundError, MemoryConflictError, MemoryValidationError) as error:
        _raise(error)
    return {"record": record, "status": "updated"}


@router.post("/memory/records/{memory_id}/merge")
def merge_memory_record(
    memory_id: str,
    request: MemoryMergeRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    service = _service(rt)
    try:
        record = service.merge(
            current_user["id"], memory_id, request.other_memory_id,
            expected_row_version=request.row_version,
            other_row_version=request.other_row_version,
            reason=request.reason, actor_id=current_user["id"],
        )
    except (MemoryNotFoundError, MemoryConflictError, MemoryValidationError) as error:
        _raise(error)
    return {"record": record, "status": "merged"}


@router.get("/memory/records/{memory_id}/history")
def memory_record_history(
    memory_id: str,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    service = _service(rt)
    try:
        return service.history(current_user["id"], memory_id)
    except MemoryNotFoundError as error:
        _raise(error)
    return {}  # pragma: no cover - _raise always raises
