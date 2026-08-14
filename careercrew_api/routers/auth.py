"""本地账号认证 HTTP 接口。业务路由的主体绑定在下一阶段处理。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from careercrew_api.auth.dependencies import get_auth_service, get_current_user, require_admin
from careercrew_api.auth.service import AccountExistsError, AuthService, AuthenticationError
from careercrew_api.schemas import CredentialsRequest, CreateUserRequest, PublicUser, TokenResponse

router = APIRouter()
_REFRESH_COOKIE = "careercrew_refresh"


def _set_refresh_cookie(response: Response, auth: AuthService, refresh_token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=refresh_token,
        max_age=auth.settings.refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=auth.settings.cookie_secure,
        samesite="lax",
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response, auth: AuthService) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE,
        httponly=True,
        secure=auth.settings.cookie_secure,
        samesite="lax",
        path="/api/auth",
    )


@router.post("/bootstrap", response_model=PublicUser, status_code=status.HTTP_201_CREATED)
def bootstrap(
    request: CredentialsRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, str]:
    """仅开发环境首次创建管理员；ID 固定为 u_001，接管既有单用户数据。"""
    try:
        return auth.bootstrap_admin(request.username, request.password)
    except PermissionError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bootstrap is disabled") from err
    except AccountExistsError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="bootstrap already completed") from err


@router.post("/token", response_model=TokenResponse)
@router.post("/login", response_model=TokenResponse, include_in_schema=False)
def login(
    request: CredentialsRequest,
    response: Response,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    """用户名密码登录；响应只返回短期 access token，刷新令牌写入 HttpOnly Cookie。"""
    try:
        payload, refresh_token = auth.login(request.username, request.password)
    except AuthenticationError as err:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password") from err
    _set_refresh_cookie(response, auth, refresh_token)
    return payload


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response,
    refresh_token: Annotated[str | None, Cookie(alias=_REFRESH_COOKIE)] = None,
    auth: AuthService = Depends(get_auth_service),
) -> dict:
    """使用并轮换刷新 Cookie；旧值立即失效。"""
    try:
        payload, new_refresh_token = auth.refresh(refresh_token)
    except AuthenticationError as err:
        _clear_refresh_cookie(response, auth)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token") from err
    _set_refresh_cookie(response, auth, new_refresh_token)
    return payload


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    refresh_token: Annotated[str | None, Cookie(alias=_REFRESH_COOKIE)] = None,
    auth: AuthService = Depends(get_auth_service),
) -> Response:
    """撤销当前刷新会话并清除浏览器 Cookie；允许无会话的幂等调用。"""
    auth.logout(refresh_token)
    _clear_refresh_cookie(response, auth)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=PublicUser)
def me(user: Annotated[dict[str, str], Depends(get_current_user)]) -> dict[str, str]:
    return user


@router.post("/users", response_model=PublicUser, status_code=status.HTTP_201_CREATED)
def create_user(
    request: CreateUserRequest,
    _: Annotated[dict[str, str], Depends(require_admin)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, str]:
    """只有已认证管理员可开户；密码哈希与刷新令牌绝不进入响应。"""
    try:
        return auth.create_user(request.username, request.password, request.role)
    except AccountExistsError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username already exists") from err
