"""账号/刷新会话/审计/限速的存储：Postgres（唯一后端）。

账号行 dict 键：id, username, password_hash, role, status, token_version,
must_change_password, created_at, updated_at。公开面（account_by_id /
list_accounts / rotate）一律剔除 password_hash。时间戳统一 ISO8601 UTC 字符串。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from careercrew_core.state.settings import AuthSettings

STATUSES = ("active", "disabled")
ROLES = ("admin", "user", "quality_reviewer")

# 向后兼容别名（历史私有名）。
_STATUSES = STATUSES
_ROLES = ROLES


class AccountExistsError(Exception):
    """用户名或首个管理员已存在。"""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


class AccountStore(ABC):
    """账号与可撤销刷新会话存储契约（见 DESIGN §4.1）。"""

    @abstractmethod
    def has_accounts(self) -> bool: ...

    @abstractmethod
    def account_by_username(self, username: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def account_by_id(self, user_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def list_accounts(self, offset: int, limit: int) -> tuple[list[dict], int]: ...

    @abstractmethod
    def create_first_admin(self, username: str, password_hash: str) -> dict[str, Any]: ...

    @abstractmethod
    def create_account(self, username: str, password_hash: str, role: str,
                       must_change: bool = False) -> dict[str, Any]: ...

    @abstractmethod
    def update_account(self, user_id: str, *, role: str | None = None,
                       status: str | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def delete_account(self, user_id: str) -> bool: ...

    @abstractmethod
    def update_password_hash(self, user_id: str, password_hash: str) -> None: ...

    @abstractmethod
    def update_avatar(self, user_id: str, avatar_ref: str) -> None: ...

    @abstractmethod
    def update_display_name(self, user_id: str, name: str) -> None: ...

    @abstractmethod
    def set_must_change_password(self, user_id: str, value: bool) -> None: ...

    @abstractmethod
    def bump_token_version(self, user_id: str) -> int: ...

    @abstractmethod
    def create_refresh_session(self, token: str, user_id: str, expires_at: datetime) -> None: ...

    @abstractmethod
    def rotate_refresh_session(self, old_token: str, new_token: str,
                               expires_at: datetime) -> dict[str, Any] | None: ...

    @abstractmethod
    def revoke_refresh_session(self, token: str) -> None: ...

    @abstractmethod
    def revoke_all_refresh_sessions(self, user_id: str) -> int: ...

    @abstractmethod
    def revoke_other_refresh_sessions(self, user_id: str, keep_token: str) -> int: ...

    @abstractmethod
    def delete_expired_refresh_sessions(self, revoked_older_than_days: int = 30) -> int: ...

    @abstractmethod
    def add_audit_event(self, actor_id: str, action: str, target_user_id: str | None,
                        context: dict) -> None: ...

    @abstractmethod
    def login_failure_locked(self, key: str) -> tuple[bool, str | None]: ...

    @abstractmethod
    def record_login_failure(self, key: str, *, max_failures: int,
                             window: timedelta, lock: timedelta) -> tuple[bool, str | None]: ...

    @abstractmethod
    def clear_login_failures(self, key: str) -> None: ...

    def get_user_settings(self, user_id: str) -> dict[str, Any]:
        return {}

    def save_user_settings(self, user_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        return {}

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {k: row[k] for k in ("id", "username", "role", "status",
                                    "token_version", "created_at", "updated_at",
                                    "must_change_password", "avatar", "display_name")
                if k in row and row.get(k) is not None}


class PostgresAccountStore(AccountStore):
    """Postgres 实现（唯一运行时后端）。所有写操作走事务。"""

    def __init__(self, dsn: str) -> None:
        """惰性连接：构造不触碰数据库（首次操作才建连+建表）。

        TestClient/lifespan 等场景会无副作用地构建 store，避免测试环境
        因数据库不可达而在应用启动阶段挂起。
        """
        self._dsn = dsn
        self._connected = False
        self._ensure_lock = threading.Lock()
        self._connect_timeout = 5
        self._pool = None  # 惰性：首次操作时从共享池注册表取

    def _get_pool(self):
        if self._pool is None:
            from careercrew_core.pg_pool import get_shared_pool, normalize_dsn

            self._pool = get_shared_pool(normalize_dsn(self._dsn))
        return self._pool

    def _ensure(self) -> None:
        if self._connected:
            return
        with self._ensure_lock:
            if self._connected:
                return
            import psycopg
            import psycopg.rows

            from careercrew_core.pg_pool import normalize_dsn

            with psycopg.connect(
                normalize_dsn(self._dsn), row_factory=psycopg.rows.dict_row, connect_timeout=self._connect_timeout
            ) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS auth_accounts ("
                    "id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, "
                    "role TEXT NOT NULL CHECK (role IN ('admin','user','quality_reviewer')), "
                    "status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')), "
                    "token_version INTEGER NOT NULL DEFAULT 0, "
                    "must_change_password BOOLEAN NOT NULL DEFAULT false, "
                    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                # 幂等迁移：既有库的旧 role CHECK（admin/user）不会随 CREATE TABLE IF NOT EXISTS
                # 更新，需 DROP + ADD。任何已有数据（admin/user）仍满足新约束，故无数据丢失。
                with conn.transaction():
                    conn.execute(
                        "ALTER TABLE auth_accounts "
                        "DROP CONSTRAINT IF EXISTS auth_accounts_role_check"
                    )
                    conn.execute(
                        "ALTER TABLE auth_accounts "
                        "ADD CONSTRAINT auth_accounts_role_check "
                        "CHECK (role IN ('admin','user','quality_reviewer'))"
                    )
                conn.execute(
                    "ALTER TABLE auth_accounts "
                    "ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT false"
                )
                conn.execute(
                    "ALTER TABLE auth_accounts "
                    "ADD COLUMN IF NOT EXISTS avatar TEXT"
                )
                conn.execute(
                    "ALTER TABLE auth_accounts "
                    "ADD COLUMN IF NOT EXISTS display_name TEXT"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS auth_refresh_sessions ("
                    "token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL "
                    "REFERENCES auth_accounts(id) ON DELETE CASCADE, "
                    "expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                    "revoked_at TIMESTAMPTZ)"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS admin_audit_events ("
                    "id BIGSERIAL PRIMARY KEY, actor_id TEXT NOT NULL, action TEXT NOT NULL, "
                    "target_user_id TEXT, context JSONB NOT NULL DEFAULT '{}'::jsonb, "
                    "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS auth_login_attempts ("
                    "key TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0, "
                    "window_start TIMESTAMPTZ, locked_until TIMESTAMPTZ, "
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS user_settings ("
                    "user_id TEXT PRIMARY KEY, "
                    "settings JSONB NOT NULL DEFAULT '{}'::jsonb, "
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                self._connected = True

    def _connect(self):
        self._ensure()
        # 返回 pool.connection() 上下文管理器：with 退出时提交/回滚并归还连接，
        # 调用点的 `with self._connect() as conn[, conn.transaction()]` 语义不变。
        return self._get_pool().connection()

    def _as_text(self, row: dict | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {k: (_iso(v) if isinstance(v, datetime) else v) for k, v in row.items()}

    def has_accounts(self) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM auth_accounts LIMIT 1").fetchone() is not None

    def create_first_admin(self, username: str, password_hash: str) -> dict[str, Any]:
        with self._connect() as conn, conn.transaction():
            if conn.execute("SELECT 1 FROM auth_accounts LIMIT 1").fetchone() is not None:
                raise AccountExistsError("an account already exists")
            row = conn.execute(
                "INSERT INTO auth_accounts (id, username, password_hash, role) "
                "VALUES ('u_001', %s, %s, 'admin') RETURNING *",
                (username, password_hash),
            ).fetchone()
        return self._public(self._as_text(row))

    def create_account(self, username: str, password_hash: str, role: str,
                       must_change: bool = False) -> dict[str, Any]:
        user_id = f"u_{uuid4().hex}"
        try:
            with self._connect() as conn, conn.transaction():
                row = conn.execute(
                    "INSERT INTO auth_accounts (id, username, password_hash, role, must_change_password) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING *",
                    (user_id, username, password_hash, role, must_change),
                ).fetchone()
        except Exception as err:
            if type(err).__name__ == "UniqueViolation":
                raise AccountExistsError("username already exists") from err
            raise
        return self._public(self._as_text(row))

    def account_by_username(self, username: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM auth_accounts WHERE username = %s", (username,)
            ).fetchone()
        return self._as_text(row)

    def account_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM auth_accounts WHERE id = %s", (user_id,)
            ).fetchone()
        return self._public(self._as_text(row)) if row else None

    def list_accounts(self, offset: int, limit: int) -> tuple[list[dict], int]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM auth_accounts").fetchone()["count"])
            rows = conn.execute(
                "SELECT * FROM auth_accounts ORDER BY created_at, id LIMIT %s OFFSET %s",
                (limit, offset),
            ).fetchall()
        return [self._public(self._as_text(r)) for r in rows], total

    def update_account(self, user_id: str, *, role: str | None = None,
                       status: str | None = None) -> dict[str, Any]:
        if role is not None and role not in _ROLES:
            raise ValueError(f"invalid role: {role}")
        if status is not None and status not in _STATUSES:
            raise ValueError(f"invalid status: {status}")
        with self._connect() as conn, conn.transaction():
            existing = conn.execute("SELECT 1 FROM auth_accounts WHERE id = %s", (user_id,)).fetchone()
            if existing is None:
                raise KeyError(user_id)
            conn.execute(
                "UPDATE auth_accounts SET role = COALESCE(%s, role), status = COALESCE(%s, status), "
                "updated_at = now() WHERE id = %s",
                (role, status, user_id),
            )
            row = conn.execute("SELECT * FROM auth_accounts WHERE id = %s", (user_id,)).fetchone()
        return self._public(self._as_text(row))

    def delete_account(self, user_id: str) -> bool:
        """硬删账号。业务数据（会话/记忆/附件等）由调用方在路由层先行清理；
        刷新会话随 FK ON DELETE CASCADE 一并删除，审计事件按设计保留（actor_id 冗余）。"""
        with self._connect() as conn, conn.transaction():
            cur = conn.execute("DELETE FROM auth_accounts WHERE id = %s", (user_id,))
        return bool(cur.rowcount)

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "UPDATE auth_accounts SET password_hash = %s, updated_at = now() WHERE id = %s",
                (password_hash, user_id),
            )

    def update_avatar(self, user_id: str, avatar_ref: str) -> None:
        with self._connect() as conn, conn.transaction():
            cur = conn.execute(
                "UPDATE auth_accounts SET avatar = %s, updated_at = now() WHERE id = %s",
                (avatar_ref, user_id),
            )
            if cur.rowcount == 0:
                raise KeyError(user_id)

    def update_display_name(self, user_id: str, name: str) -> None:
        with self._connect() as conn, conn.transaction():
            cur = conn.execute(
                "UPDATE auth_accounts SET display_name = %s, updated_at = now() WHERE id = %s",
                (name, user_id),
            )
            if cur.rowcount == 0:
                raise KeyError(user_id)

    def set_must_change_password(self, user_id: str, value: bool) -> None:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "UPDATE auth_accounts SET must_change_password = %s, updated_at = now() WHERE id = %s",
                (value, user_id),
            )

    def bump_token_version(self, user_id: str) -> int:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "UPDATE auth_accounts SET token_version = token_version + 1, updated_at = now() "
                "WHERE id = %s RETURNING token_version",
                (user_id,),
            ).fetchone()
            if row is None:
                raise KeyError(user_id)
        return int(row["token_version"])

    def create_refresh_session(self, token: str, user_id: str, expires_at: datetime) -> None:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO auth_refresh_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                (hash_token(token), user_id, expires_at),
            )

    def rotate_refresh_session(self, old_token: str, new_token: str,
                               expires_at: datetime) -> dict[str, Any] | None:
        old_hash = hash_token(old_token)
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT s.expires_at, a.id, a.username, a.role, a.status, a.token_version, "
                "a.created_at, a.updated_at, a.must_change_password, a.avatar, a.display_name "
                "FROM auth_refresh_sessions s JOIN auth_accounts a ON a.id = s.user_id "
                "WHERE s.token_hash = %s AND s.revoked_at IS NULL AND a.status = 'active'",
                (old_hash,),
            ).fetchone()
            if row is None or row["expires_at"] <= _utcnow():
                conn.execute("DELETE FROM auth_refresh_sessions WHERE token_hash = %s", (old_hash,))
                return None
            conn.execute("DELETE FROM auth_refresh_sessions WHERE token_hash = %s", (old_hash,))
            conn.execute(
                "INSERT INTO auth_refresh_sessions (token_hash, user_id, expires_at) "
                "VALUES (%s, %s, %s)",
                (hash_token(new_token), row["id"], expires_at),
            )
        return self._public(self._as_text(row))

    def revoke_refresh_session(self, token: str) -> None:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "UPDATE auth_refresh_sessions SET revoked_at = now() "
                "WHERE token_hash = %s AND revoked_at IS NULL",
                (hash_token(token),),
            )

    def revoke_all_refresh_sessions(self, user_id: str) -> int:
        with self._connect() as conn, conn.transaction():
            cur = conn.execute(
                "UPDATE auth_refresh_sessions SET revoked_at = now() "
                "WHERE user_id = %s AND revoked_at IS NULL",
                (user_id,),
            )
        return cur.rowcount

    def revoke_other_refresh_sessions(self, user_id: str, keep_token: str) -> int:
        with self._connect() as conn, conn.transaction():
            cur = conn.execute(
                "UPDATE auth_refresh_sessions SET revoked_at = now() "
                "WHERE user_id = %s AND token_hash != %s AND revoked_at IS NULL",
                (user_id, hash_token(keep_token)),
            )
        return cur.rowcount

    def delete_expired_refresh_sessions(self, revoked_older_than_days: int = 30) -> int:
        with self._connect() as conn, conn.transaction():
            cur = conn.execute(
                "DELETE FROM auth_refresh_sessions WHERE expires_at <= now() "
                "OR (revoked_at IS NOT NULL AND revoked_at <= now() - make_interval(days => %s))",
                (revoked_older_than_days,),
            )
        return cur.rowcount

    def add_audit_event(self, actor_id: str, action: str, target_user_id: str | None,
                        context: dict) -> None:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO admin_audit_events (actor_id, action, target_user_id, context) "
                "VALUES (%s, %s, %s, %s::jsonb)",
                (actor_id, action, target_user_id, json.dumps(context, ensure_ascii=False)),
            )

    def login_failure_locked(self, key: str) -> tuple[bool, str | None]:
        """只读检查是否处于锁定期；不计数、不重置窗口。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT locked_until FROM auth_login_attempts WHERE key = %s", (key,)
            ).fetchone()
        if row and row["locked_until"] and row["locked_until"] > _utcnow():
            return True, _iso(row["locked_until"])
        return False, None

    def record_login_failure(self, key: str, *, max_failures: int,
                             window: timedelta, lock: timedelta) -> tuple[bool, str | None]:
        now = _utcnow()
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT * FROM auth_login_attempts WHERE key = %s FOR UPDATE", (key,)
            ).fetchone()
            if row and row["locked_until"] and row["locked_until"] > now:
                return True, _iso(row["locked_until"])
            if row is None:
                conn.execute(
                    "INSERT INTO auth_login_attempts (key, failures, window_start) "
                    "VALUES (%s, 1, %s)",
                    (key, now),
                )
                return False, None
            window_start = row["window_start"] or now
            if window_start < now - window:
                failures, window_start = 1, now
            else:
                failures = int(row["failures"]) + 1
            locked_until: datetime | None = now + lock if failures >= max_failures else None
            conn.execute(
                "UPDATE auth_login_attempts SET failures = %s, window_start = %s, "
                "locked_until = %s, updated_at = now() WHERE key = %s",
                (failures, window_start, locked_until, key),
            )
            return failures >= max_failures, _iso(locked_until) if locked_until else None

    def clear_login_failures(self, key: str) -> None:
        with self._connect() as conn, conn.transaction():
            conn.execute("DELETE FROM auth_login_attempts WHERE key = %s", (key,))

    def get_user_settings(self, user_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT settings FROM user_settings WHERE user_id = %s", (user_id,)
            ).fetchone()
            if not row or not row.get("settings"):
                return {}
            val = row["settings"]
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except Exception:
                    return {}
            return dict(val) if isinstance(val, dict) else {}

    def save_user_settings(self, user_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        settings_json = json.dumps(settings, ensure_ascii=False)
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO user_settings (user_id, settings, updated_at) "
                "VALUES (%s, %s::jsonb, now()) "
                "ON CONFLICT (user_id) DO UPDATE "
                "SET settings = EXCLUDED.settings, updated_at = now()",
                (user_id, settings_json),
            )
        return settings


def create_account_store(settings: AuthSettings) -> AccountStore:
    """认证存储唯一后端：Postgres。"""
    return PostgresAccountStore(settings.database_url)
