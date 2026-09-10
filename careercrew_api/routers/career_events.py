"""Privacy-safe product event ingestion and owner-scoped funnel counts."""
from __future__ import annotations

from fastapi import APIRouter

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.routers.career import Store
from careercrew_core.career.product_events import ProductEvent, event_funnel, record_event

router = APIRouter()


@router.post("/events", status_code=201)
def create_product_event(payload: ProductEvent, user: CurrentUser, store: Store):
    record_event(store.pool, user["id"], payload)
    return {"ok": True}


@router.get("/events/funnel")
def product_funnel(user: CurrentUser, store: Store):
    return event_funnel(store.pool, user["id"])
