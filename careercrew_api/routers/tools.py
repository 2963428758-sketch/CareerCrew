"""Tool operations center: status, effective permissions, history and admin policy."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from careercrew_api.auth.dependencies import AdminUser, CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.tools.operations import ToolOperationsCenter, is_tool_store_unavailable

router = APIRouter()


class ToolPolicyRequest(BaseModel):
    enabled: bool
    reason: str = Field(default="", max_length=500)


def _center(rt: CareerCrewRuntime) -> ToolOperationsCenter:
    rt._ensure_stores()
    store = getattr(rt, "conversation_store", None)
    settings = getattr(rt, "settings", None)
    if store is None or settings is None:
        rt._ensure_heavy()
        store = getattr(rt, "conversation_store", None)
        settings = getattr(rt, "settings", None)
    if store is None or settings is None:
        raise HTTPException(status_code=503, detail="工具中心尚未就绪")
    center = getattr(rt, "tool_operations_center", None)
    if center is None:
        center = ToolOperationsCenter(store, settings)
        rt.tool_operations_center = center
    return center


def _run(operation):
    try:
        return operation()
    except Exception as exc:  # noqa: BLE001 - map only known storage failures
        if is_tool_store_unavailable(exc):
            raise HTTPException(status_code=503, detail="工具中心暂时不可用") from exc
        raise


@router.get("/tools")
def tool_status(
    _user: CurrentUser,
    module: str = Query(default="chat", max_length=50),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    return _run(lambda: {"module": module, "tools": _center(rt).status(module)})


@router.get("/tools/effective")
def effective_tools(
    _user: CurrentUser,
    module: str = Query(default="chat", max_length=50),
    requested: list[str] = Query(default=[]),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    return _run(lambda: {"module": module, "tools": _center(rt).effective_tools(module, requested or None)})


@router.get("/tools/calls")
def tool_calls(
    user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=200),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    return _run(lambda: _center(rt).call_history(user["id"], limit))


@router.get("/tools/audit")
def tool_audit(
    _admin: AdminUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    return _run(lambda: _center(rt).audit())


@router.put("/tools/{tool_id}")
def update_tool_policy(
    tool_id: str,
    payload: ToolPolicyRequest,
    admin: AdminUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        return _run(lambda: _center(rt).set_policy(
            admin["id"], tool_id, payload.enabled, payload.reason,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
