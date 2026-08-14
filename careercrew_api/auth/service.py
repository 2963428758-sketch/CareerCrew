"""账号持久化、密码哈希与 JWT/刷新会话服务。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import hashlib
import secrets
import sqlite3
from typing import Any
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from careercrew_core.state.settings import AuthSettings


class AuthenticationError(Exception):
    """凭据、访问令牌或刷新 Cookie 无效。"""


class AccountExistsError(Exception):
    """用户名或首个管理员已存在。"""


class AccountStore:
    """SQLite 账号与可撤销的刷新令牌会话存储。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS accounts ("
                "id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, "
                "role TEXT NOT NULL CHECK(role IN ('admin', 'user')), created_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS refresh_sessions ("
                "token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL, "
                "created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES accounts(id) ON DELETE CASCADE)"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _public(row: sqlite3.Row | dict[str, Any]) -> dict[str, str]:
        return {"id": row["id"], "username": row["username"], "role": row["role"]}

    def has_accounts(self) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None

    def create_first_admin(self, username: str, password_hash: str) -> dict[str, str]:
        now = _utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None:
                conn.execute("ROLLBACK")
                raise AccountExistsError("an account already exists")
            conn.execute(
                "INSERT INTO accounts (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                ("u_001", username, password_hash, "admin", now),
            )
            row = conn.execute("SELECT id, username, role FROM accounts WHERE id = 'u_001'").fetchone()
            conn.execute("COMMIT")
        return self._public(row)

    def create_account(self, username: str, password_hash: str, role: str) -> dict[str, str]:
        user_id = f"u_{uuid4().hex}"
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO accounts (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, username, password_hash, role, _utcnow().isoformat()),
                )
                row = conn.execute("SELECT id, username, role FROM accounts WHERE id = ?", (user_id,)).fetchone()
        except sqlite3.IntegrityError as err:
            raise AccountExistsError("username already exists") from err
        return self._public(row)

    def account_by_username(self, username: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, role FROM accounts WHERE username = ?", (username,)
            ).fetchone()
        return dict(row) if row else None

    def account_by_id(self, user_id: str) -> dict[str, str] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT id, username, role FROM accounts WHERE id = ?", (user_id,)).fetchone()
        return self._public(row) if row else None

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE accounts SET password_hash = ? WHERE id = ?", (password_hash, user_id))

    def create_refresh_session(self, token: str, user_id: str, expires_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO refresh_sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (_token_hash(token), user_id, expires_at.isoformat(), _utcnow().isoformat()),
            )

    def rotate_refresh_session(self, old_token: str, new_token: str, expires_at: datetime) -> dict[str, str] | None:
        old_hash = _token_hash(old_token)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT s.user_id, s.expires_at, a.id, a.username, a.role "
                "FROM refresh_sessions s JOIN accounts a ON a.id = s.user_id WHERE s.token_hash = ?",
                (old_hash,),
            ).fetchone()
            if row is None or datetime.fromisoformat(row["expires_at"]) <= _utcnow():
                conn.execute("DELETE FROM refresh_sessions WHERE token_hash = ?", (old_hash,))
                conn.execute("COMMIT")
                return None
            conn.execute("DELETE FROM refresh_sessions WHERE token_hash = ?", (old_hash,))
            conn.execute(
                "INSERT INTO refresh_sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (_token_hash(new_token), row["user_id"], expires_at.isoformat(), _utcnow().isoformat()),
            )
            conn.execute("COMMIT")
        return self._public(row)

    def revoke_refresh_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM refresh_sessions WHERE token_hash = ?", (_token_hash(token),))


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


def _new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
