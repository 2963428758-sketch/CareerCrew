"""流式路由共享的请求期助手：mentions/附件服务端校验 + NDJSON 响应头。

此前 `_resolve_mentions` / `_resolve_attachments` / `_ndjson_response`
在 chat / resume / interview 三处逐字复制，consult / knowledge 又各写一遍
内联版——语义漂移与漏改风险随份数线性增长，统一收敛到这里。
"""
from __future__ import annotations

from collections.abc import Generator

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from careercrew_api.attachment_context import AttachmentRejected
from careercrew_api.mentions import MentionRejected
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError


def resolve_mentions_or_422(
    rt: CareerCrewRuntime, user_id: str, mentions
) -> list[dict]:
    """T3.4 §15.2：mentions 服务端二次校验；拒绝越权引用 → 422。"""
    if not mentions:
        return []
    try:
        return rt.resolve_mentions(user_id, [m.model_dump() for m in mentions])
    except MentionRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def resolve_attachments_or_422(
    rt: CareerCrewRuntime, user_id: str, refs
) -> list[dict]:
    """T3.2：附件服务端校验所有权 + 读取内容（文本块）；整体拒绝 → 422。"""
    if not refs:
        return []
    try:
        return rt.resolve_attachment_blocks(user_id, [r.model_dump() for r in refs])
    except AttachmentRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def ndjson_response(gen: Generator[str, None, None]) -> StreamingResponse:
    """统一 NDJSON 流式响应头（禁缓存 + 禁代理缓冲）。"""
    return StreamingResponse(
        gen,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
