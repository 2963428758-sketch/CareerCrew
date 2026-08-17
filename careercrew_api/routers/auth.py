"""本地账号认证 HTTP 接口。业务路由的主体绑定在下一阶段处理。"""
from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter, Cookie, Depends, File, HTTPException, Request, Response, UploadFile, status,
)
from fastapi.responses import FileResponse

from careercrew_api.auth.dependencies import get_auth_service, get_current_user, require_admin
from careercrew_api.auth.service import (
    AccountDisabledError,
    AccountExistsError,
    AuthService,
    AuthenticationError,
    LastAdminError,
    LoginLockedError,
    SelfAdminError,
)
from careercrew_api.oss import download_bytes, oss_config, upload_bytes
from careercrew_api.schemas import (
    AccountListItem,
    ChangePasswordRequest,
    CredentialsRequest,
    CreateUserRequest,
    PasswordResetRequest,
    PublicUser,
    TokenResponse,
    UpdateDisplayNameRequest,
    UserListResponse,
    UserPatchRequest,
)
from careercrew_api.storage import DATA_ROOT, resolve_under

router = APIRouter()
_REFRESH_COOKIE = "careercrew_refresh"

# ── 头像上传 ──

# 允许的头像格式与最大体积（5MB）
_AVATAR_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_AVATAR_MAX_BYTES = 5 * 1024 * 1024

# 未配置 OSS 时的本地回退目录：data/uploads/avatars/{user_id}/{uuid}.{ext}
AVATAR_ROOT = DATA_ROOT / "uploads" / "avatars"

# 头像扩展名 -> MIME（OSS 代理读取时使用）
_AVATAR_MIME = {v: k for k, v in _AVATAR_EXTENSIONS.items()}


@router.post("/avatar")
async def upload_avatar(
    file: Annotated[UploadFile, File(...)],
    user: Annotated[dict[str, str], Depends(get_current_user)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, bool]:
    """上传/替换当前用户头像。配置 OSS 时直传阿里云 OSS，否则落本地存储回退。"""
    content_type = (file.content_type or "").lower()
    if content_type not in _AVATAR_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 PNG / JPG / WebP / GIF 格式的头像",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像文件为空")
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像不能超过 5MB")

    ext = _AVATAR_EXTENSIONS[content_type]
    user_id = user["id"]
    config = oss_config()
    if config:
        # 对象键：{dir_prefix}/avatars/{user_id}/{uuid}.{ext}
        prefix = config.get("dir_prefix") or ""
        key = f"{prefix}/avatars/{user_id}/{uuid4().hex}{ext}" if prefix else f"avatars/{user_id}/{uuid4().hex}{ext}"
        try:
            upload_bytes(config, key, data, content_type)
        except Exception as err:  # 网络/签名失败等：明确报错，不静默降级
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OSS 上传失败：{err}",
            ) from err
        auth.store.update_avatar(user_id, f"oss:{key}")
    else:
        user_dir = resolve_under(AVATAR_ROOT, user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        name = f"{uuid4().hex}{ext}"
        (user_dir / name).write_bytes(data)
        auth.store.update_avatar(user_id, f"local:{user_id}/{name}")
    return {"ok": True}


@router.get("/avatar/{user_id}")
def get_avatar(
    user_id: str,
    _user: Annotated[dict[str, str], Depends(get_current_user)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
):
    """读取用户头像：OSS 头像经同源代理返回（避免跨域 CORS），本地回退头像直接返回文件。"""
    account = auth.store.account_by_id(user_id)
    avatar_ref = (account or {}).get("avatar") or ""
    if avatar_ref.startswith("oss:"):
        config = oss_config()
        if config is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="头像存储服务不可用")
        key = avatar_ref[len("oss:"):]
        media_type = _AVATAR_MIME.get("." + key.rsplit(".", 1)[-1].lower(), "application/octet-stream")
        try:
            data = download_bytes(config, key)
        except Exception as err:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OSS 读取失败：{err}") from err
        return Response(content=data, media_type=media_type)
    if avatar_ref.startswith("local:"):
        # 格式固定为 local:{user_id}/{uuid}.{ext}，由上传侧生成，不含额外路径段
        name = avatar_ref[len("local:"):]
        path = resolve_under(AVATAR_ROOT, *name.split("/"))
        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="头像不存在或已被删除")
        return FileResponse(str(path))
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该用户尚未设置头像")


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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前环境不允许初始化管理员") from err
    except AccountExistsError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="系统已初始化过管理员，请直接登录") from err


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
    except AccountDisabledError as err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你的账号已被锁定，请联系管理员",
        ) from err
    except LoginLockedError as err:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"登录尝试次数过多，请稍后再试（{err.retry_after_seconds} 秒后解除）",
            headers={"Retry-After": str(err.retry_after_seconds)},
        ) from err
    except AuthenticationError as err:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码不正确") from err
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新登录") from err
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
    """只有已认证管理员可开户；密码留空时默认 123456，首次登录强制改密。"""
    try:
        return auth.create_user(actor, request.username, request.password, request.role)
    except AccountExistsError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该用户名已被占用，请换一个") from err
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


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
                            detail="不能修改自己的账号，请在「账号」设置中操作") from err
    except LastAdminError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="操作失败：系统至少需要保留一名有效管理员") from err
    except KeyError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="账号不存在或已被删除") from err
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: str,
    request: PasswordResetRequest,
    admin: Annotated[dict[str, str], Depends(require_admin)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, bool]:
    """管理员重置密码：留空则重置为默认 123456；无论哪种，下次登录强制改密。"""
    try:
        auth.admin_reset_password(admin, user_id, request.password)
    except SelfAdminError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="不能重置自己的密码，请在「账号」设置中修改") from err
    except KeyError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="账号不存在或已被删除") from err
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
    return {"ok": True}


@router.post("/password")
def change_password(
    request: ChangePasswordRequest,
    user: Annotated[dict[str, str], Depends(get_current_user)],
    refresh_token: Annotated[str | None, Cookie(alias=_REFRESH_COOKIE)] = None,
    auth: AuthService = Depends(get_auth_service),
) -> dict[str, bool]:
    """当前用户修改自己的密码：撤销除当前会话外的其他刷新会话，并解除强制改密标记。"""
    try:
        auth.change_own_password(
            user, request.old_password, request.new_password,
            current_refresh_token=refresh_token,
        )
    except AuthenticationError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="当前密码不正确") from err
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
    return {"ok": True}


@router.post("/display-name", response_model=PublicUser)
def update_display_name(
    request: UpdateDisplayNameRequest,
    user: Annotated[dict[str, str], Depends(get_current_user)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    """修改自己的显示名（用于界面展示，登录用户名不变）。"""
    try:
        return auth.update_own_display_name(user, request.name)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
