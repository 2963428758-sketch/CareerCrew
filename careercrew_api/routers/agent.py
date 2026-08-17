"""agent 路由（T3.5 §16.1）：客户端 Capability 汇总。

- GET /api/agent/capabilities?module=chat
  返回该 module 服务端可见工具（id/name/enabled/requires_hitl），单一事实来源为
  settings.tools.registry + settings.tools.hitl.requires_confirmation。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.tools.capabilities import build_capabilities

router = APIRouter()


@router.get("/agent/capabilities")
def capabilities(
    current_user: CurrentUser,
    module: str = Query(default="chat"),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """汇总 module 的客户端可见工具 capability（服务端单一事实来源）。

    module 非法时回退全量注册工具（不 404，便于前端任意 module 下拉）；语义上仍由
    server allowlist 兜底，客户端选择不能突破 allowlist（§16.3）。
    """
    rt._ensure_heavy()
    module = (module or "chat").strip()
    tools = build_capabilities(module, rt.settings)
    return {"module": module, "tools": tools}
