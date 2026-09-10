"""Owner-scoped paged search at the existing career API path."""
from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.routers.career import Store
from careercrew_core.career.search import search_page
from careercrew_core.state.settings import load_auth_settings

router = APIRouter()


@lru_cache(maxsize=1)
def _search_signing_secret() -> str:
    # 配置只在进程启动周期内读取；密钥变更需要重启，同时让所有 worker 保持一致。
    return load_auth_settings().signing_secret()


@router.get("/search")
def global_search(q: str, user: CurrentUser, store: Store,
                  limit: int = 20, cursor: str | None = None):
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="搜索词不能为空")
    try:
        return search_page(
            store.pool, user["id"], query[:200], limit, cursor,
            signing_secret=_search_signing_secret(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
