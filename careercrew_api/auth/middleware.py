"""Cookie 会话接口的 Origin 校验（CSRF 纵深防御，samesite=lax 之外的第二道闸）。"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_PROTECTED_PATHS = {"/api/auth/refresh", "/api/auth/logout"}


class TrustedOriginMiddleware(BaseHTTPMiddleware):
    """对受保护 POST 校验 Origin 头（缺失放行，非浏览器客户端不受影响）。"""

    def __init__(self, app, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self._allowed = set(allowed_origins)

    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and request.url.path in _PROTECTED_PATHS:
            origin = request.headers.get("origin")
            if origin and origin not in self._allowed:
                return JSONResponse({"detail": "untrusted origin"}, status_code=403)
        return await call_next(request)
