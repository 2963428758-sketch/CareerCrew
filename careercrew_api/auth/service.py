"""账号持久化、密码哈希与 JWT/刷新会话服务。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


# 兼容别名：旧代码路径以 service 模块名引用这两个工具
_new_refresh_token = new_refresh_token
_token_hash = hash_token


class AuthService:
    """认证编排；刷新令牌始终为仅 Cookie 携带的随机不透明值。"""

    def __init__(self, settings: AuthSettings, store: AccountStore) -> None:
        self.settings = settings
        self.store = store
        self.password_hasher = PasswordHasher()

    def bootstrap_admin(self, username: str, password: str) -> dict[str, str]:
        if not self.settings.is_development:
            raise PermissionError("bootstrap is only available in development")
        return self.store.create_first_admin(username, self.password_hasher.hash(password))

    def create_user(self, username: str, password: str, role: str = "user") -> dict[str, str]:
        return self.store.create_account(username, self.password_hasher.hash(password), role)

    def login(self, username: str, password: str) -> tuple[dict[str, Any], str]:
        account = self.store.account_by_username(username)
        if not account:
            raise AuthenticationError("invalid username or password")
        try:
            valid = self.password_hasher.verify(account["password_hash"], password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid:
            raise AuthenticationError("invalid username or password")
        if self.password_hasher.check_needs_rehash(account["password_hash"]):
            self.store.update_password_hash(account["id"], self.password_hasher.hash(password))
        user = {key: account[key] for key in ("id", "username", "role")}
        return self._token_response(user)

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
        if not user or user["role"] != claims.get("role"):
            raise AuthenticationError("invalid access token")
        return user

    def _token_response(
        self, user: dict[str, str], refresh_token: str | None = None, session_exists: bool = False
    ) -> tuple[dict[str, Any], str]:
        now = _utcnow()
        expires = now + timedelta(minutes=self.settings.access_token_minutes)
        access_token = jwt.encode(
            {"sub": user["id"], "role": user["role"], "type": "access", "iat": now, "exp": expires},
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
