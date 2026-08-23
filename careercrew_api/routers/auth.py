"""本地账号认证 HTTP 接口。业务路由的主体绑定在下一阶段处理。"""
from __future__ import annotations

import logging
import shutil
from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from careercrew_api.auth.dependencies import get_auth_service, get_current_user, require_admin
from careercrew_api.auth.service import (
    AccountDisabledError,
    AccountExistsError,
    AuthenticationError,
    AuthService,
    LastAdminError,
    LoginLockedError,
    SelfAdminError,
)
from careercrew_api.oss import delete_object, download_bytes, oss_config, upload_bytes
from careercrew_api.runtime import get_runtime
from careercrew_api.schemas import (
    AccountListItem,
    ChangePasswordRequest,
    CreateUserRequest,
    CredentialsRequest,
    PasswordResetRequest,
    PublicUser,
    TokenResponse,
    UpdateDisplayNameRequest,
    UserListResponse,
    UserPatchRequest,
)
from careercrew_api.storage import DATA_ROOT, L, resolve_under
from careercrew_api.upload_io import read_bounded

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


def _store_avatar_local(user_id: str, ext: str, data: bytes, auth: AuthService) -> None:
    """本地回退存储：写盘 + 落头像引用（阻塞 IO，须在线程池中调用）。"""
    user_dir = resolve_under(AVATAR_ROOT, user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid4().hex}{ext}"
    (user_dir / name).write_bytes(data)
    auth.store.update_avatar(user_id, f"local:{user_id}/{name}")


@router.post("/avatar")
async def upload_avatar(
    file: Annotated[UploadFile, File(...)],
    user: Annotated[dict[str, str], Depends(get_current_user)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, bool]:
    """上传/替换当前用户头像。配置 OSS 时直传阿里云 OSS，否则落本地存储回退。

    OSS 网络上传与本地写盘均为阻塞 IO，下放线程池避免卡事件循环；
    体积校验在分块读取阶段生效（不把超大 body 缓冲进内存）。
    """
    content_type = (file.content_type or "").lower()
    if content_type not in _AVATAR_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 PNG / JPG / WebP / GIF 格式的头像",
        )
    data = await read_bounded(file, _AVATAR_MAX_BYTES)
    if data is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像不能超过 5MB")
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像文件为空")

    ext = _AVATAR_EXTENSIONS[content_type]
    user_id = user["id"]
    config = oss_config()
    if config:
        # 对象键：{dir_prefix}/avatars/{user_id}/{uuid}.{ext}
        prefix = config.get("dir_prefix") or ""
        key = f"{prefix}/avatars/{user_id}/{uuid4().hex}{ext}" if prefix else f"avatars/{user_id}/{uuid4().hex}{ext}"
        try:
            await run_in_threadpool(upload_bytes, config, key, data, content_type)
        except Exception:  # 网络/签名失败等：明确报错，不静默降级
            # 异常细节（bucket/endpoint/XML 响应）只进服务端日志，不回给客户端
            logging.getLogger("careercrew_api").warning("avatar OSS upload failed", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="头像上传到对象存储失败，请稍后重试",
            ) from None
        await run_in_threadpool(auth.store.update_avatar, user_id, f"oss:{key}")
    else:
        await run_in_threadpool(_store_avatar_local, user_id, ext, data, auth)
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
        except Exception:
            logging.getLogger("careercrew_api").warning("avatar OSS download failed", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="头像存储服务暂时不可用"
            ) from None
        return Response(content=data, media_type=media_type)
    if avatar_ref.startswith("local:"):
        # 格式固定为 local:{user_id}/{uuid}.{ext}，由上传侧生成，不含额外路径段
        name = avatar_ref[len("local:"):]
        path = resolve_under(AVATAR_ROOT, *name.split("/"))
        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="头像不存在或已被删除")
        return FileResponse(str(path))
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该用户尚未设置头像")


def _purge_avatar_files(avatar_ref: str) -> None:
    """删除账号后清理其头像存储（本地按用户目录整体清，OSS 删当前对象）；失败仅记录不阻断。"""
    log = logging.getLogger("careercrew_api")
    if avatar_ref.startswith("local:"):
        # ref 形如 local:{user_id}/{name}；换过头像的用户目录里可能残留历史文件，整体清理
        owner = avatar_ref[len("local:"):].split("/", 1)[0]
        try:
            shutil.rmtree(resolve_under(AVATAR_ROOT, owner), ignore_errors=True)
        except OSError as err:
            log.warning("delete avatar dir for %s failed: %s", owner, err)
    elif avatar_ref.startswith("oss:"):
        config = oss_config()
        if config is None:
            return
        key = avatar_ref[len("oss:"):]
        try:
            delete_object(config, key)
        except Exception as err:  # noqa: BLE001 - 头像清理失败不影响账号删除结果
            log.warning("delete avatar object %s failed: %s", key, err)


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


def _client_ip(request: Request, auth: AuthService) -> str:
    """登录限流键用的客户端 IP。

    auth.trust_proxy_headers=true（LB/Nginx 后部署）时取 X-Forwarded-For 首个
    地址；否则用 TCP 对端地址——XFF 头可被伪造，直连部署下信任它等于绕过限流。
    """
    if auth.settings.trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for", "")
        first_hop = xff.split(",")[0].strip()
        if first_hop:
            return first_hop
    return request.client.host if request.client else ""


@router.post("/token", response_model=TokenResponse)
@router.post("/login", response_model=TokenResponse, include_in_schema=False)
def login(
    request: CredentialsRequest,
    response: Response,
    http_request: Request,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    """用户名密码登录；响应只返回短期 access token，刷新令牌写入 HttpOnly Cookie。"""
    client_ip = _client_ip(http_request, auth)
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
    """只有已认证管理员可开户；密码留空时默认 123456 并强制首登改密，自定义密码则不强制。"""
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
    """管理员重置密码：留空使用默认 123456 并强制改密；自定义密码可直接使用。"""
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


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    admin: Annotated[dict[str, str], Depends(require_admin)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    """删除账号并清理其全部业务数据：会话/消息/运行、反馈、记忆、附件（DB 行 + 磁盘文件）与头像。

    保护：不能删自己；不能删除最后一名有效管理员。审计事件按设计保留。
    业务数据清理依赖重组件运行时；不可用（未初始化/测试 Fake）时跳过清理仅删账号。
    """
    try:
        rt = get_runtime()
        rt._ensure_heavy()
    except Exception:  # noqa: BLE001 - 运行时不可用：跳过业务数据清理
        pass
    else:
        storage_keys: list[str] = []
        try:
            if rt.conversation_store is not None:
                rt.conversation_store.db_delete_all_for_user(user_id)
            if rt.memory_db is not None:
                rt.memory_db.delete_all_for_user(user_id)
            if rt.attachment_store is not None:
                storage_keys = rt.attachment_store.delete_all_for_user(user_id)
        except Exception as err:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="删除用户数据失败，已中止删除操作，请稍后重试",
            ) from err
        # 磁盘附件按 storage_key 删除（相对 attachments 根）；失败仅记录，不阻断账号删除
        for key in storage_keys:
            try:
                path = resolve_under(L.attachments, *key.split("/"))
                path.unlink(missing_ok=True)
            except OSError as err:
                logging.getLogger("careercrew_api").warning("delete attachment %s failed: %s", key, err)

    # 删除前取头像引用（账号行删掉后就查不到了），删除成功后再清理存储
    try:
        avatar_ref = (auth.store.account_by_id(user_id) or {}).get("avatar") or ""
    except Exception:  # noqa: BLE001 - 查询失败不阻断删除主流程
        avatar_ref = ""
    try:
        result = auth.delete_user(admin, user_id)
    except SelfAdminError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="不能删除自己的账号") from err
    except LastAdminError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="操作失败：系统至少需要保留一名有效管理员") from err
    except KeyError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="账号不存在或已被删除") from err
    _purge_avatar_files(avatar_ref)
    return {"ok": True, **result}


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
