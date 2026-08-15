"""账号/刷新会话/审计/限速的存储抽象：SQLite（测试）与 Postgres（运行时）。

账号行 dict 键：id, username, password_hash, role, status, token_version,
created_at, updated_at。公开面（account_by_id / list_accounts / rotate）
一律剔除 password_hash。时间戳统一 ISO8601 UTC 字符串。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from pathlib import Path
import hashlib
import json
import secrets
import sqlite3
from typing import Any
from uuid import uuid4

from careercrew_core.state.settings import AuthSettings

_STATUSES = ("active", "disabled")
_ROLES = ("admin", "user")


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
    def create_account(self, username: str, password_hash: str, role: str) -> dict[str, Any]: ...

    @abstractmethod
    def update_account(self, user_id: str, *, role: str | None = None,
                       status: str | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def update_password_hash(self, user_id: str, password_hash: str) -> None: ...

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

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {k: row[k] for k in ("id", "username", "role", "status",
                                    "token_version", "created_at", "updated_at")
                if k in row and row.get(k) is not None}


class SqliteAccountStore(AccountStore):
    """SQLite 实现（仅测试/显式本地配置）。旧库自动补 status/token_version/updated_at。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS accounts ("
                "id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, "
                "role TEXT NOT NULL CHECK(role IN ('admin', 'user')), created_at TEXT NOT NULL)"
            )
            for column, ddl in (
                ("status", "ALTER TABLE accounts ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"),
                ("token_version", "ALTER TABLE accounts ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"),
                ("updated_at", "ALTER TABLE accounts ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"),
            ):
                if column not in self._columns(conn, "accounts"):
                    conn.execute(ddl)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS refresh_sessions ("
                "token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL, "
                "created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES accounts(id) ON DELETE CASCADE)"
            )
            if "revoked_at" not in self._columns(conn, "refresh_sessions"):
                conn.execute("ALTER TABLE refresh_sessions ADD COLUMN revoked_at TEXT")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS admin_audit_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL, action TEXT NOT NULL, "
                "target_user_id TEXT, context TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS auth_login_attempts ("
                "key TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0, "
                "window_start TEXT, locked_until TEXT, updated_at TEXT NOT NULL)"
            )

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _account_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data.setdefault("status", "active")
        data.setdefault("token_version", 0)
        data.setdefault("updated_at", data.get("created_at", ""))
        return data

    def has_accounts(self) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None

    def create_first_admin(self, username: str, password_hash: str) -> dict[str, Any]:
        now = _utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None:
                conn.execute("ROLLBACK")
                raise AccountExistsError("an account already exists")
            conn.execute(
                "INSERT INTO accounts (id, username, password_hash, role, status, token_version, created_at, updated_at) "
                "VALUES (?, ?, ?, 'admin', 'active', 0, ?, ?)",
                ("u_001", username, password_hash, now, now),
            )
            row = conn.execute("SELECT * FROM accounts WHERE id = 'u_001'").fetchone()
            conn.execute("COMMIT")
        return self._public(self._account_row(row))

    def create_account(self, username: str, password_hash: str, role: str) -> dict[str, Any]:
        user_id = f"u_{uuid4().hex}"
        now = _utcnow().isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO accounts (id, username, password_hash, role, status, token_version, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'active', 0, ?, ?)",
                    (user_id, username, password_hash, role, now, now),
                )
                row = conn.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
        except sqlite3.IntegrityError as err:
            raise AccountExistsError("username already exists") from err
        return self._public(self._account_row(row))

    def account_by_username(self, username: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE username = ?", (username,)).fetchone()
        return self._account_row(row) if row else None

    def account_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
        return self._public(self._account_row(row)) if row else None

    def list_accounts(self, offset: int, limit: int) -> tuple[list[dict], int]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
            rows = conn.execute(
                "SELECT * FROM accounts ORDER BY created_at, id LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [self._public(self._account_row(r)) for r in rows], total

    def update_account(self, user_id: str, *, role: str | None = None,
                       status: str | None = None) -> dict[str, Any]:
        if role is not None and role not in _ROLES:
            raise ValueError(f"invalid role: {role}")
        if status is not None and status not in _STATUSES:
            raise ValueError(f"invalid status: {status}")
        now = _utcnow().isoformat()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise KeyError(user_id)
            data = self._account_row(row)
            conn.execute(
                "UPDATE accounts SET role = ?, status = ?, updated_at = ? WHERE id = ?",
                (role if role is not None else data["role"],
                 status if status is not None else data["status"], now, user_id),
            )
            refreshed = conn.execute("SELECT * FROM accounts WHERE id = ?", (user_id,)).fetchone()
        return self._public(self._account_row(refreshed))

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE accounts SET password_hash = ?, updated_at = ? WHERE id = ?",
                (password_hash, _utcnow().isoformat(), user_id),
            )

    def bump_token_version(self, user_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT token_version FROM accounts WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise KeyError(user_id)
            version = int(row["token_version"]) + 1
            conn.execute(
                "UPDATE accounts SET token_version = ?, updated_at = ? WHERE id = ?",
                (version, _utcnow().isoformat(), user_id),
            )
        return version

    def create_refresh_session(self, token: str, user_id: str, expires_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO refresh_sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (hash_token(token), user_id, expires_at.isoformat(), _utcnow().isoformat()),
            )

    def rotate_refresh_session(self, old_token: str, new_token: str,
                               expires_at: datetime) -> dict[str, Any] | None:
        old_hash = hash_token(old_token)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT s.user_id, s.expires_at, a.id, a.username, a.role, a.status, a.token_version, "
                "a.created_at, a.updated_at "
                "FROM refresh_sessions s JOIN accounts a ON a.id = s.user_id "
                "WHERE s.token_hash = ? AND s.revoked_at IS NULL AND a.status = 'active'",
                (old_hash,),
            ).fetchone()
            if row is None or datetime.fromisoformat(row["expires_at"]) <= _utcnow():
                conn.execute("DELETE FROM refresh_sessions WHERE token_hash = ?", (old_hash,))
                conn.execute("COMMIT")
                return None
            conn.execute("DELETE FROM refresh_sessions WHERE token_hash = ?", (old_hash,))
            conn.execute(
                "INSERT INTO refresh_sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (hash_token(new_token), row["user_id"], expires_at.isoformat(), _utcnow().isoformat()),
            )
            conn.execute("COMMIT")
        account = {
            "id": row["id"], "username": row["username"], "role": row["role"],
            "status": row["status"], "token_version": row["token_version"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
        return self._public(account)

    def revoke_refresh_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE refresh_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (_utcnow().isoformat(), hash_token(token)),
            )

    def revoke_all_refresh_sessions(self, user_id: str) -> int:
        now = _utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE refresh_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now, user_id),
            )
        return cur.rowcount

    def revoke_other_refresh_sessions(self, user_id: str, keep_token: str) -> int:
        now = _utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE refresh_sessions SET revoked_at = ? "
                "WHERE user_id = ? AND token_hash != ? AND revoked_at IS NULL",
                (now, user_id, hash_token(keep_token)),
            )
        return cur.rowcount

    def delete_expired_refresh_sessions(self, revoked_older_than_days: int = 30) -> int:
        now = _utcnow()
        cutoff = (now - timedelta(days=revoked_older_than_days)).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM refresh_sessions WHERE expires_at <= ? OR (revoked_at IS NOT NULL AND revoked_at <= ?)",
                (now.isoformat(), cutoff),
            )
        return cur.rowcount

    def add_audit_event(self, actor_id: str, action: str, target_user_id: str | None,
                        context: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO admin_audit_events (actor_id, action, target_user_id, context, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (actor_id, action, target_user_id, json.dumps(context, ensure_ascii=False),
                 _utcnow().isoformat()),
            )

    def login_failure_locked(self, key: str) -> tuple[bool, str | None]:
        """只读检查是否处于锁定期；不计数、不重置窗口。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT locked_until FROM auth_login_attempts WHERE key = ?", (key,)
            ).fetchone()
        if row and row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > _utcnow():
            return True, row["locked_until"]
        return False, None

    def record_login_failure(self, key: str, *, max_failures: int,
                             window: timedelta, lock: timedelta) -> tuple[bool, str | None]:
        now = _utcnow()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM auth_login_attempts WHERE key = ?", (key,)).fetchone()
            if row and row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > now:
                locked_until = row["locked_until"]
                conn.execute("COMMIT")
                return True, locked_until
            if not row:
                conn.execute(
                    "INSERT INTO auth_login_attempts (key, failures, window_start, locked_until, updated_at) "
                    "VALUES (?, 1, ?, NULL, ?)",
                    (key, now.isoformat(), now.isoformat()),
                )
                conn.execute("COMMIT")
                return False, None
            window_start = row["window_start"] or now.isoformat()
            if datetime.fromisoformat(window_start) < now - window:
                failures, window_start = 1, now.isoformat()
            else:
                failures = int(row["failures"]) + 1
            locked_until: str | None = None
            if failures >= max_failures:
                locked = now + lock
                locked_until = locked.isoformat()
            conn.execute(
                "UPDATE auth_login_attempts SET failures = ?, window_start = ?, locked_until = ?, updated_at = ? "
                "WHERE key = ?",
                (failures, window_start, locked_until, now.isoformat(), key),
            )
            conn.execute("COMMIT")
            return failures >= max_failures, locked_until

    def clear_login_failures(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM auth_login_attempts WHERE key = ?", (key,))


class PostgresAccountStore(AccountStore):
    """Postgres 实现（运行时默认）。所有写操作走事务。"""

    def __init__(self, dsn: str) -> None:
        import psycopg
        import psycopg.rows

        self._dsn = dsn
        with psycopg.connect(dsn, row_factory=psycopg.rows.dict_row) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS auth_accounts ("
                "id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, "
                "role TEXT NOT NULL CHECK (role IN ('admin','user')), "
                "status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')), "
                "token_version INTEGER NOT NULL DEFAULT 0, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
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

    def _connect(self):
        import psycopg
        import psycopg.rows

        return psycopg.connect(self._dsn, row_factory=psycopg.rows.dict_row)

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

    def create_account(self, username: str, password_hash: str, role: str) -> dict[str, Any]:
        user_id = f"u_{uuid4().hex}"
        try:
            with self._connect() as conn, conn.transaction():
                row = conn.execute(
                    "INSERT INTO auth_accounts (id, username, password_hash, role) "
                    "VALUES (%s, %s, %s, %s) RETURNING *",
                    (user_id, username, password_hash, role),
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

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "UPDATE auth_accounts SET password_hash = %s, updated_at = now() WHERE id = %s",
                (password_hash, user_id),
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
                "a.created_at, a.updated_at "
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


def create_account_store(settings: AuthSettings) -> AccountStore:
    if settings.backend == "postgres":
        return PostgresAccountStore(settings.database_url)
    return SqliteAccountStore(settings.account_db_path)
