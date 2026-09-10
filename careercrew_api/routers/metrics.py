"""Prometheus scrape endpoint with no user/document labels."""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from careercrew_core.state.settings import load_auth_settings
from careercrew_core.observability.metrics import get_metrics_registry

router = APIRouter()


def _production_environment() -> bool:
    override = os.environ.get("CAREERCREW_ENV", "").strip()
    if override:
        return override.lower() in {"production", "prod", "staging"}
    try:
        return not load_auth_settings().is_development
    except Exception:  # noqa: BLE001 - fail closed if environment cannot be resolved
        return True


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(request: Request) -> PlainTextResponse:
    configured_token = os.environ.get("CAREERCREW_METRICS_TOKEN", "").strip()
    if configured_token:
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, configured_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="metrics scrape authorization required",
                headers={"WWW-Authenticate": "Bearer"},
            )
    elif _production_environment():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="metrics scrape token is not configured",
        )
    return PlainTextResponse(
        get_metrics_registry().render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


__all__ = ["router"]
