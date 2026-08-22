"""认证服务与当前身份的 FastAPI 依赖。"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, TypeAlias

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from careercrew_api.auth.service import AuthenticationError, AuthService
from careercrew_api.auth.store import create_account_store
from careercrew_core.state.settings import load_auth_settings

_bearer = HTTPBearer(auto_error=False)

# 强制改密期间仍可访问的端点：查询自身、修改密码、登出、认证本身
_PASSWORD_CHANGE_ALLOWLIST = {
    "/api/auth/me", "/api/auth/password", "/api/auth/logout",
}


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    settings = load_auth_settings()
    return AuthService(settings, create_account_store(settings))


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, str]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    try:
        user = auth.current_user(credentials.credentials)
    except AuthenticationError as err:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新登录") from err
    if user.get("must_change_password") and request.url.path not in _PASSWORD_CHANGE_ALLOWLIST:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="首次登录需先修改密码")
    if user["role"] == "quality_reviewer" and not (
        request.url.path.startswith("/api/quality/") or request.url.path in _PASSWORD_CHANGE_ALLOWLIST
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="质检员只能访问质量审查接口")
    return user


def require_admin(
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict[str, str]:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该操作需要管理员权限")
    return user


def require_quality_reviewer(
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict[str, str]:
    if user["role"] != "quality_reviewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该操作需要质检员权限")
    return user


CurrentUser: TypeAlias = Annotated[dict[str, str], Depends(get_current_user)]
AdminUser: TypeAlias = Annotated[dict[str, str], Depends(require_admin)]
QualityReviewer: TypeAlias = Annotated[dict[str, str], Depends(require_quality_reviewer)]
