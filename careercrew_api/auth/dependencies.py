"""认证服务与当前身份的 FastAPI 依赖。"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, TypeAlias

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from careercrew_api.auth.service import AuthService, AuthenticationError
from careercrew_api.auth.store import create_account_store
from careercrew_core.state.settings import load_auth_settings

_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    settings = load_auth_settings()
    return AuthService(settings, create_account_store(settings))


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, str]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    try:
        return auth.current_user(credentials.credentials)
    except AuthenticationError as err:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid access token") from err


def require_admin(
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict[str, str]:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="administrator required")
    return user


CurrentUser: TypeAlias = Annotated[dict[str, str], Depends(get_current_user)]
AdminUser: TypeAlias = Annotated[dict[str, str], Depends(require_admin)]
