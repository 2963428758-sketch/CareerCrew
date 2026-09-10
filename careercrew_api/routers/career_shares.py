"""Public share lifecycle and privacy controls."""
from __future__ import annotations

import secrets
import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.routers.career import PrepStore, Store
from careercrew_core.career.product_events import safe_event

router = APIRouter()
# ── 导师只读分享 ──


class ShareCreateRequest(BaseModel):
    kind: str
    ref_id: str
    expires_days: int = 7
    # 安全默认脱敏：除非调用方显式关闭
    mask_pii: bool = True


# ── PII 脱敏（分享/导出共用）：邮箱、手机号、座机、身份证、微信号、地址 ──

_PII_PATTERNS = (
    (r"[\w.+-]+@[\w-]+\.[\w.-]+", "[邮箱已隐藏]"),
    (r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号已隐藏]"),
    (r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)", "[电话已隐藏]"),
    # 15 位或 18 位身份证（18 位末位可为 X/x）
    (r"(?<!\d)\d{15}(?:\d{2}[0-9Xx])?(?!\d)", "[证件号已隐藏]"),
    (r"(?:微信号|微信ID|weixin|wxid|微信)\s*[:：]\s*[\w-]{4,}", "[微信号已隐藏]"),
    (r"(?:[\u4e00-\u9fa5]{1,6}(?:省|市|区|县|镇|乡|街道|路|街|道)[^，。；;\n]{0,24}(?:号|大厦|大楼|小区|花园|广场|中心|园区)[^，。；;\n]{0,12})",
     "[地址已隐藏]"),
)


def _mask_pii_text(text: str) -> str:
    import re

    for pattern, replacement in _PII_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def _share_payload(row: dict, prep) -> dict:
    """构造公开只读载荷：仅必要字段；mask_pii 时对文本做 PII 脱敏。"""
    prep = prep
    owner = str(row["owner_id"])
    mask = bool(row["mask_pii"])

    def clean(text) -> str:
        text = str(text or "")
        return _mask_pii_text(text) if mask else text

    if row["kind"] == "resume_version":
        version = prep.get_version_any(owner, str(row["ref_id"]))
        if version is None:
            return {"kind": "resume_version", "missing": True}
        return {"kind": "resume_version", "label": clean(version.get("label")),
                "content": clean(version.get("content")),
                "created_at": version.get("created_at")}
    opportunity = prep.get_opportunity(owner, str(row["ref_id"]))
    if opportunity is None:
        return {"kind": "opportunity", "missing": True}
    versions = list(prep.list_versions(owner, str(opportunity["id"])))
    return {
        "kind": "opportunity",
        "company": clean(opportunity.get("company")),
        "title": clean(opportunity.get("title")),
        "jd": clean(opportunity.get("jd")),
        "city": clean(opportunity.get("city")),
        "salary": clean(opportunity.get("salary")),
        "stage": clean(opportunity.get("stage")),
        "versions": [{"label": clean(v.get("label")), "content": clean(v.get("content")),
                      "created_at": v.get("created_at")} for v in versions],
    }


@router.post("/shares", status_code=201)
def create_share(payload: ShareCreateRequest, user: CurrentUser, store: Store, prep: PrepStore):
    """创建导师只读分享链接。kind=opportunity 分享整包；kind=resume_version 只分享单版本。

    令牌明文只在本次响应中出现一次（数据库只存 SHA-256 哈希），丢失后只能撤销重建。
    """
    if payload.kind not in ("opportunity", "resume_version"):
        raise HTTPException(status_code=422, detail="kind 必须为 opportunity 或 resume_version")
    if not 1 <= payload.expires_days <= 30:
        raise HTTPException(status_code=422, detail="有效期 1-30 天")
    if payload.kind == "opportunity":
        if prep.get_opportunity(user["id"], payload.ref_id) is None:
            raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    else:
        if prep.get_version_any(user["id"], payload.ref_id) is None:
            raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    from datetime import timedelta

    expires = (datetime_now_utc() + timedelta(days=payload.expires_days)).isoformat()
    token = secrets.token_urlsafe(32)
    row = store.create_share(user["id"], token, payload.kind, payload.ref_id, expires, payload.mask_pii)
    safe_event(store.pool, user['id'], 'share_created', 'preparation')
    return {"token": token, "id": row["token_hash"], "kind": row["kind"], "ref_id": row["ref_id"],
            "mask_pii": bool(row["mask_pii"]), "expires_at": row["expires_at"]}


@router.get("/shares")
def list_shares(user: CurrentUser, store: Store):
    # 不含任何可访问凭据（明文令牌不可恢复），仅状态与访问审计
    return store.list_shares(user["id"])


@router.delete("/shares/{token}")
def revoke_share(token: str, user: CurrentUser, store: Store):
    if not store.revoke_share(user["id"], token):
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    return {"ok": True}


# 公开分享端点的每 IP 频率限制（进程内实现；多 worker 部署时可换共享存储）
_SHARE_RATE_LIMIT = 60  # 次/分钟/IP
_share_rate_bucket: dict[str, list[float]] = {}
_share_rate_lock = threading.Lock()
_SHARE_HEADERS = {
    "Cache-Control": "no-store, max-age=0", "Pragma": "no-cache",
    "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _share_rate_limit(ip: str) -> bool:
    """滑动窗口限流：超过阈值返回 False。"""
    import time

    now = time.time()
    with _share_rate_lock:
        # Bound memory even when many clients each issue a single request.
        for key in list(_share_rate_bucket):
            if not _share_rate_bucket[key] or now - _share_rate_bucket[key][-1] >= 60:
                del _share_rate_bucket[key]
        if ip not in _share_rate_bucket and len(_share_rate_bucket) >= 10000:
            return False
        hits = [t for t in _share_rate_bucket.get(ip, []) if now - t < 60]
        if len(hits) >= _SHARE_RATE_LIMIT:
            _share_rate_bucket[ip] = hits
            return False
        hits.append(now)
        _share_rate_bucket[ip] = hits
        return True


@router.get("/share/{token}")
def resolve_share(token: str, request: Request, store: Store, prep: PrepStore):
    """公开只读访问（无鉴权）：令牌过期/撤销/不存在一律 404；带访问审计与防爬响应头。"""
    ip = request.client.host if request.client else "unknown"
    if not _share_rate_limit(ip):
        raise HTTPException(status_code=429, detail="访问过于频繁，请稍后再试", headers={**_SHARE_HEADERS, "Retry-After": "60"})
    row = store.resolve_share(token)
    if row is None:
        raise HTTPException(status_code=404, detail="分享不存在或已失效", headers=_SHARE_HEADERS)
    payload = _share_payload(row, prep)
    if payload.get("missing"):
        raise HTTPException(status_code=404, detail="分享内容不存在或已失效", headers=_SHARE_HEADERS)
    safe_event(store.pool, row['owner_id'], 'share_accessed', 'public_share')
    return JSONResponse(
        {"mask_pii": bool(row["mask_pii"]), "expires_at": row["expires_at"], **payload},
        headers=_SHARE_HEADERS,
    )


def datetime_now_utc():
    from datetime import UTC, datetime

    return datetime.now(UTC)
