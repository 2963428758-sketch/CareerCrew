"""账号持久化、密码哈希与 JWT/刷新会话服务。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from careercrew_api.auth.store import (
    AccountExistsError,
    AccountStore,
    SqliteAccountStore,
    create_account_store,
    hash_token,
    new_refresh_token,
)
from careercrew_core.state.settings import AuthSettings


class AuthenticationError(Exception):
    """凭据、访问令牌或刷新 Cookie 无效。"""


class LoginLockedError(Exception):
    """登录失败过多，账号按用户名/来源 IP 被短期锁定。"""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"too many login attempts; retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


class SelfAdminError(Exception):
    """管理员不能通过用户管理端点修改自己。"""


class LastAdminError(Exception):
    """操作会使系统失去最后一名有效管理员。"""


# 兼容别名：旧代码路径以 service 模块名引用这两个工具
_new_refresh_token = new_refresh_token
_token_hash = hash_token


class AuthService:
    """认证编排；刷新令牌始终为仅 Cookie 携带的随机不透明值。"""

    def __init__(self, settings: AuthSettings, store: AccountStore) -> None:
        self.settings = settings
        self.store = store
        self.password_hasher = PasswordHasher(
            time_cost=3, memory_cost=65536, parallelism=4, hash_len=32,
        )

    def bootstrap_admin(self, username: str, password: str) -> dict[str, str]:
        if not self.settings.is_development:
            raise PermissionError("bootstrap is only available in development")
        return self.store.create_first_admin(username, self.password_hasher.hash(password))

    def create_user(self, actor: dict[str, str], username: str, password: str,
                    role: str = "user") -> dict[str, str]:
        created = self.store.create_account(username, self.password_hasher.hash(password), role)
        self._audit(actor["id"], "user.create", created["id"], {"role": role})
        return created

    def login(self, username: str, password: str, client_ip: str = "") -> tuple[dict[str, Any], str]:
        locked_keys = [f"login:u:{username.lower()}"]
        if client_ip:
            locked_keys.append(f"login:ip:{client_ip}")
        for key in locked_keys:
            locked, locked_until = self.store.login_failure_locked(key)
            if locked:
                raise LoginLockedError(self._retry_after(locked_until))
        account = self.store.account_by_username(username)
        valid = False
        if account and account.get("status") == "active":
            try:
                valid = self.password_hasher.verify(account["password_hash"], password)
            except (VerificationError, InvalidHashError):
                valid = False
        if not valid:
            for key in locked_keys:
                locked, locked_until = self.store.record_login_failure(
                    key, max_failures=self.settings.login_max_failures,
                    window=timedelta(minutes=self.settings.login_failure_window_minutes),
                    lock=timedelta(minutes=self.settings.login_lock_minutes),
                )
                if locked:
                    raise LoginLockedError(self._retry_after(locked_until))
            raise AuthenticationError("invalid username or password")
        for key in locked_keys:
            self.store.clear_login_failures(key)
        if self.password_hasher.check_needs_rehash(account["password_hash"]):
            self.store.update_password_hash(account["id"], self.password_hasher.hash(password))
        user = {key: account[key] for key in ("id", "username", "role")}
        return self._token_response(user)

    def _retry_after(self, locked_until: str | None) -> int:
        if not locked_until:
            return self.settings.login_lock_minutes * 60
        try:
            delta = (datetime.fromisoformat(locked_until) - _utcnow()).total_seconds()
        except ValueError:
            delta = 0
        return max(1, int(delta))

    def refresh(self, refresh_token: str | None) -> tuple[dict[str, Any], str]:
        if not refresh_token:
            raise AuthenticationError("missing refresh token")
        replacement = _new_refresh_token()
        user = self.store.rotate_refresh_session(refresh_token, replacement, self._refresh_expiry())
        if not user:
            raise AuthenticationError("invalid refresh token")
        return self._token_response(user, refresh_token=replacement, session_exists=True)

    def logout(self, refresh_token: str | None) -> None:
        if refresh_token:
            self.store.revoke_refresh_session(refresh_token)

    def current_user(self, access_token: str) -> dict[str, str]:
        try:
            claims = jwt.decode(
                access_token,
                self.settings.signing_secret(),
                algorithms=["HS256"],
                options={"require": ["sub", "role", "type", "exp"]},
            )
        except jwt.PyJWTError as err:
            raise AuthenticationError("invalid access token") from err
        if claims.get("type") != "access":
            raise AuthenticationError("invalid access token")
        user = self.store.account_by_id(str(claims["sub"]))
        if (
            not user
            or user["role"] != claims.get("role")
            or user.get("status") != "active"
            or int(user.get("token_version") or 0) != int(claims.get("tv") or 0)
        ):
            raise AuthenticationError("invalid access token")
        return user

    def change_own_password(
        self, user: dict[str, str], old_password: str, new_password: str,
        current_refresh_token: str | None = None,
    ) -> None:
        account = self.store.account_by_username(user["username"])
        if not account:
            raise AuthenticationError("account not found")
        try:
            valid = self.password_hasher.verify(account["password_hash"], old_password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid:
            raise AuthenticationError("invalid password")
        self.store.update_password_hash(user["id"], self.password_hasher.hash(new_password))
        self.store.bump_token_version(user["id"])
        if current_refresh_token:
            self.store.revoke_other_refresh_sessions(user["id"], current_refresh_token)
        else:
            self.store.revoke_all_refresh_sessions(user["id"])

    def admin_reset_password(self, actor: dict[str, str], user_id: str, new_password: str) -> None:
        if actor["id"] == user_id:
            raise SelfAdminError("administrators must use /api/auth/password for themselves")
        self.store.update_password_hash(user_id, self.password_hasher.hash(new_password))
        self.store.bump_token_version(user_id)
        self.store.revoke_all_refresh_sessions(user_id)
        self._audit(actor["id"], "user.reset_password", user_id, {})

    def update_user(
        self, actor: dict[str, str], user_id: str, *,
        role: str | None = None, status: str | None = None,
    ) -> dict[str, Any]:
        target = self.store.account_by_id(user_id)
        if not target:
            raise KeyError(user_id)
        if role is None and status is None:
            raise ValueError("nothing to update")
        new_role = role if role is not None else target["role"]
        new_status = status if status is not None else target["status"]
        # 系统级不变量优先：任何操作都不能让系统失去最后一名有效管理员
        if target["role"] == "admin" and (new_role != "admin" or new_status != "active"):
            self._ensure_remaining_active_admin(excluding=user_id)
        if actor["id"] == user_id:
            raise SelfAdminError("administrators cannot modify their own account here")
        updated = self.store.update_account(user_id, role=new_role, status=new_status)
        self.store.bump_token_version(user_id)
        if new_status == "disabled":
            self.store.revoke_all_refresh_sessions(user_id)
        self._audit(
            actor["id"], "user.update", user_id,
            {"fields": sorted({k for k in ("role", "status") if locals().get(k) is not None})},
        )
        return updated

    def _ensure_remaining_active_admin(self, excluding: str) -> None:
        items, _total = self.store.list_accounts(0, 1000)
        active_admins = sum(
            1 for a in items
            if a["id"] != excluding and a["role"] == "admin" and a["status"] == "active"
        )
        if active_admins == 0:
            raise LastAdminError("operation would remove the last active administrator")

    def list_users(self, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        offset = max(page - 1, 0) * page_size
        return self.store.list_accounts(offset, page_size)

    def _audit(self, actor_id: str, action: str, target_user_id: str | None, context: dict) -> None:
        self.store.add_audit_event(actor_id, action, target_user_id, context)

    def _token_response(
        self, user: dict[str, str], refresh_token: str | None = None, session_exists: bool = False
    ) -> tuple[dict[str, Any], str]:
        now = _utcnow()
        expires = now + timedelta(minutes=self.settings.access_token_minutes)
        account = self.store.account_by_id(user["id"]) or {}
        access_token = jwt.encode(
            {
                "sub": user["id"], "role": user["role"], "type": "access",
                "tv": int(account.get("token_version") or 0), "iat": now, "exp": expires,
            },
            self.settings.signing_secret(),
            algorithm="HS256",
        )
        token = refresh_token or _new_refresh_token()
        if not session_exists:
            self.store.create_refresh_session(token, user["id"], self._refresh_expiry())
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": int((expires - now).total_seconds()),
            "user": user,
        }, token

    def _refresh_expiry(self) -> datetime:
        return _utcnow() + timedelta(days=self.settings.refresh_token_days)


def _utcnow() -> datetime:
    return datetime.now(UTC)
