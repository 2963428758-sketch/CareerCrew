"""Context @ 引用路由（T3.4 §15 / §34）：可引用资源列表。

- GET /api/context/resources?types=knowledge,resume&q=... → §15.1 形状
  服务端返回的资源已过 visibility filter + ownership filter（本人 private + public
  知识文档 + 本人简历），客户端再提交的 mention id 仍会在发送路径二次校验（§15.2）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError

router = APIRouter()

_ALLOWED_TYPES = ("knowledge", "resume")


@router.get("/resources")
def list_context_resources(
    current_user: CurrentUser,
    types: str = Query("", description="逗号分隔：knowledge,resume；空=两者"),
    q: str = Query("", description="按名称过滤"),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """§15.1：返回当前用户可引用资源（已过 visibility + ownership 过滤）。"""
    wanted: list[str] | None = None
    if types.strip():
        wanted = []
        for t in types.split(","):
            t = t.strip()
            if t and t not in _ALLOWED_TYPES:
                raise HTTPException(status_code=422, detail="types 仅支持 knowledge,resume")
            if t:
                wanted.append(t)
        if not wanted:
            wanted = None
    try:
        items = rt.list_context_resources(current_user["id"], types=wanted, q=q)
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"items": items}
