"""Owner-scoped usage summaries and admin-managed budget policies."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from careercrew_api.auth.dependencies import AdminUser, CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.usage.ledger import UsageLedger, UsageValidationError

router = APIRouter()


class UsageBudgetRequest(BaseModel):
    scope_type: Literal["user", "module"] = "user"
    scope_key: str = Field(default="*", min_length=1, max_length=50)
    period: Literal["daily", "monthly"] = "daily"
    token_limit: int | None = Field(default=None, ge=0)
    cost_limit_usd: float | None = Field(default=None, ge=0)
    soft_limit_ratio: float = Field(default=0.8, gt=0, le=1)
    downgrade_model: str | None = Field(default=None, min_length=1, max_length=150)
    enabled: bool = True


def _ledger(rt: CareerCrewRuntime) -> UsageLedger:
    ensure_stores = getattr(rt, "_ensure_stores", None)
    if callable(ensure_stores):
        ensure_stores()
    db = getattr(rt, "usage_db", None) or getattr(rt, "memory_db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="用量治理服务暂不可用")
    return UsageLedger(db)


def _raise(error: Exception) -> None:
    if isinstance(error, UsageValidationError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


@router.get("/usage/summary")
def usage_summary(
    current_user: CurrentUser,
    period: Literal["daily", "monthly"] = Query("daily"),
    module: str | None = Query(None, max_length=50),
    owner_id: str | None = Query(None, max_length=64),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    target_owner = owner_id if current_user.get("role") == "admin" and owner_id else current_user["id"]
    try:
        return _ledger(rt).summary(target_owner, period=period, module=module)
    except UsageValidationError as error:
        _raise(error)
    return {}  # pragma: no cover - _raise always raises


@router.get("/usage/budgets")
def usage_budgets(
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    try:
        items = _ledger(rt).budgets(current_user["id"])
    except UsageValidationError as error:
        _raise(error)
    return {"items": items, "total": len(items)}


@router.put("/usage/budgets/{owner_id}")
def save_usage_budget(
    owner_id: str,
    request: UsageBudgetRequest,
    _admin: AdminUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict[str, Any]:
    try:
        return _ledger(rt).set_budget(
            owner_id, scope_type=request.scope_type, scope_key=request.scope_key,
            period=request.period, token_limit=request.token_limit,
            cost_limit_usd=request.cost_limit_usd,
            soft_limit_ratio=request.soft_limit_ratio,
            downgrade_model=request.downgrade_model, enabled=request.enabled,
        )
    except UsageValidationError as error:
        _raise(error)
    return {}  # pragma: no cover - _raise always raises


__all__ = ["router"]
