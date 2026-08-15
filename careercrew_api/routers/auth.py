"""本地账号认证 HTTP 接口。业务路由的主体绑定在下一阶段处理。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status

from careercrew_api.auth.dependencies import get_auth_service, get_current_user, require_admin
from careercrew_api.auth.service import (
    AccountExistsError,
    AuthService,
    AuthenticationError,
    LastAdminError,
    LoginLockedError,
    SelfAdminError,
)
from careercrew_api.schemas import (
    AccountListItem,
    ChangePasswordRequest,
    CredentialsRequest,
    CreateUserRequest,
    PasswordResetRequest,
    PublicUser,
    TokenResponse,
    UserListResponse,
    UserPatchRequest,
)

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


@router.get("/bootstrap")
def bootstrap_status(
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, bool]:
    """仅公开是否可创建首个开发管理员，不暴露任何账号信息。"""
    return {"available": auth.settings.is_development and not auth.store.has_accounts()}


@router.post("/token", response_model=TokenResponse)
@router.post("/login", response_model=TokenResponse, include_in_schema=False)
def login(
    request: CredentialsRequest,
    response: Response,
    http_request: Request,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    """用户名密码登录；响应只返回短期 access token，刷新令牌写入 HttpOnly Cookie。"""
    client_ip = http_request.client.host if http_request.client else ""
    try:
        payload, refresh_token = auth.login(request.username, request.password, client_ip=client_ip)
    except LoginLockedError as err:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many login attempts",
            headers={"Retry-After": str(err.retry_after_seconds)},
        ) from err
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
    actor: Annotated[dict[str, str], Depends(require_admin)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, str]:
    """只有已认证管理员可开户；密码哈希与刷新令牌绝不进入响应。"""
    try:
        return auth.create_user(actor, request.username, request.password, request.role)
    except AccountExistsError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username already exists") from err


@router.get("/users", response_model=UserListResponse)
def list_users(
    page: int = 1,
    page_size: int = 20,
    _admin: Annotated[dict[str, str], Depends(require_admin)] = None,
    auth: Annotated[AuthService, Depends(get_auth_service)] = None,
) -> dict:
    """管理员分页查看账号（不含密码哈希/令牌）。"""
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    items, total = auth.list_users(page, page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.patch("/users/{user_id}", response_model=AccountListItem)
def patch_user(
    user_id: str,
    request: UserPatchRequest,
    admin: Annotated[dict[str, str], Depends(require_admin)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    """启用/禁用或修改角色。不能改自己；不能失去最后一名有效管理员。"""
    try:
        return auth.update_user(admin, user_id, role=request.role, status=request.status)
    except SelfAdminError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="administrators cannot modify their own account here") from err
    except LastAdminError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="operation would remove the last active administrator") from err
    except KeyError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="account not found") from err


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: str,
    request: PasswordResetRequest,
    admin: Annotated[dict[str, str], Depends(require_admin)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, bool]:
    """管理员重置密码：撤销该用户全部会话并使其 access token 立即失效。"""
    try:
        auth.admin_reset_password(admin, user_id, request.password)
    except SelfAdminError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="administrators must use /api/auth/password for themselves") from err
    except KeyError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="account not found") from err
    return {"ok": True}


@router.post("/password")
def change_password(
    request: ChangePasswordRequest,
    user: Annotated[dict[str, str], Depends(get_current_user)],
    refresh_token: Annotated[str | None, Cookie(alias=_REFRESH_COOKIE)] = None,
    auth: AuthService = Depends(get_auth_service),
) -> dict[str, bool]:
    """当前用户修改自己的密码：撤销除当前会话外的其他刷新会话。"""
    try:
        auth.change_own_password(
            user, request.old_password, request.new_password,
            current_refresh_token=refresh_token,
        )
    except AuthenticationError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="invalid password") from err
    return {"ok": True}
