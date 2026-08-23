"""聊天附件持久化层：抽象契约 + Postgres 实现 + 内存 Fake（T3.1 §14）。

chat_attachments 表（§14.4 DDL + user_id/thread_id VARCHAR(64) 一致化，对齐
conversation 包的既有决策）：id UUID、user_id/thread_id VARCHAR(64)、
original_filename、storage_key、mime_type、size_bytes、status、parser_type、
parser_error、knowledge_document_id、created_at、last_used_at、expires_at。

状态全集（§14.3）：uploading / uploaded / parsing / ready / failed / deleted /
saved_to_knowledge。TTL（§14.5）：最后活动后 7 天；save-to-knowledge 后
expires_at=NULL（取消 TTL）。

与 conversation/db.py 同库（Postgres）；单测用 FakeAttachmentDb（内存）。
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any
from uuid import UUID

from careercrew_core.conversation.uuid7 import uuid7


def _now() -> datetime:
    """单一 aware-UTC 时钟：始终返回带时区信息的 datetime 对象。

    时间戳列均为 TIMESTAMPTZ：直接传 datetime 对象，避免 ISO 字符串再经
    ``.astimezone(utc)`` 转换时对 naive datetime 的解释歧义（可能静默偏移，
    破坏 7 天 TTL）。所有 created_at / last_used_at / expires_at 的比较与写入
    都使用本 helper 产出的 aware-UTC datetime。
    """
    return datetime.now(UTC)


# §14.5：最后活动后 7 天清理
DEFAULT_TTL_DAYS = 7


class OwnershipError(Exception):
    """附件不属于该用户 / 不存在时抛出（跨用户一律视为不存在，不泄露资源）。"""


def _row_to_dict(row: Any) -> dict:
    """psycopg dict_row 行转普通 dict（UUID 归一 str）。"""
    return {k: (str(v) if isinstance(v, UUID) else v) for k, v in dict(row).items()}


def _synchronized(fn):
    """PostgresAttachmentDb 单连接非线程安全：公开方法串行化（RLock）。"""

    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self.write_lock:
            return fn(self, *args, **kwargs)

    return wrapper


class AttachmentDb(ABC):
    """聊天附件持久化契约。"""

    @abstractmethod
    def create_attachment(
        self,
        attachment_id: str,
        user_id: str,
        thread_id: str,
        original_filename: str,
        storage_key: str,
        mime_type: str | None,
        size_bytes: int | None,
        status: str,
        parser_type: str | None = None,
        parser_error: str | None = None,
        knowledge_document_id: str | None = None,
        created_at: datetime | None = None,
        last_used_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> dict: ...

    @abstractmethod
    def get_attachment(self, user_id: str, attachment_id: str) -> dict | None: ...

    @abstractmethod
    def list_attachments(self, user_id: str, thread_id: str) -> list[dict]: ...

    @abstractmethod
    def update_status(self, user_id: str, attachment_id: str, status: str,
                      parser_error: str | None = None,
                      parser_type: str | None = None,
                      knowledge_document_id: str | None = None,
                      last_used_at: datetime | None = None) -> dict: ...

    @abstractmethod
    def delete_attachment(self, user_id: str, attachment_id: str) -> bool: ...

    @abstractmethod
    def delete_all_for_user(self, user_id: str) -> list[dict]: ...

    @abstractmethod
    def count_nondeleted(self, user_id: str, thread_id: str) -> int: ...

    @abstractmethod
    def clear_expires_at(self, user_id: str, attachment_id: str) -> dict: ...

    @abstractmethod
    def list_expired(self, now: datetime) -> list[dict]: ...


class PostgresAttachmentDb(AttachmentDb):
    """Postgres 实现（psycopg 3，惰性连接 + 幂等建表）。"""

    def __init__(self, dsn: str) -> None:
        from careercrew_core.pg_pool import normalize_dsn

        # 入口归一：兼容 postgresql+psycopg://（容器 compose 注入的 SQLAlchemy 方言写法）
        self._dsn = normalize_dsn(dsn)
        self._connected = False
        self.write_lock = threading.RLock()

    def _connect(self):
        if not self._connected:
            self._ensure()
        import psycopg

        return psycopg.connect(self._dsn, row_factory=psycopg.rows.dict_row)

    @_synchronized
    def _ensure(self):
        if self._connected:
            return
        try:
            import psycopg
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "PostgresAttachmentDb 需要 psycopg：pip install 'psycopg[binary]'"
            ) from e
        with psycopg.connect(self._dsn, row_factory=psycopg.rows.dict_row) as conn, conn.transaction():
            # §14.4 DDL：chat_attachments（user_id/thread_id VARCHAR(64) 一致化，
            # 对齐 conversation 表决策——方案 DDL 的 UUID 与 u_001 账号体系矛盾）。
            conn.execute(
                "CREATE TABLE IF NOT EXISTS chat_attachments ("
                "id UUID PRIMARY KEY, "
                "user_id VARCHAR(64) NOT NULL, "
                "thread_id VARCHAR(64) NOT NULL, "
                "original_filename VARCHAR(500) NOT NULL, "
                "storage_key VARCHAR(1000) NOT NULL, "
                "mime_type VARCHAR(150), "
                "size_bytes BIGINT, "
                "status VARCHAR(30) NOT NULL, "
                "parser_type VARCHAR(100), "
                "parser_error TEXT, "
                "knowledge_document_id UUID, "
                "created_at TIMESTAMPTZ NOT NULL, "
                "last_used_at TIMESTAMPTZ NOT NULL, "
                "expires_at TIMESTAMPTZ)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_attachments_thread "
                "ON chat_attachments(thread_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_attachments_expires "
                "ON chat_attachments(expires_at)"
            )
        self._connected = True

    @_synchronized
    def create_attachment(self, attachment_id, user_id, thread_id, original_filename,
                          storage_key, mime_type, size_bytes, status, parser_type=None,
                          parser_error=None, knowledge_document_id=None, created_at=None,
                          last_used_at=None, expires_at=None) -> dict:
        now = created_at or _now()
        lu = last_used_at or now
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO chat_attachments (id, user_id, thread_id, original_filename, "
                "storage_key, mime_type, size_bytes, status, parser_type, parser_error, "
                "knowledge_document_id, created_at, last_used_at, expires_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (attachment_id, user_id, thread_id, original_filename, storage_key,
                 mime_type, size_bytes, status, parser_type, parser_error,
                 knowledge_document_id, now, lu, expires_at),
            )
        return self.get_attachment(user_id, attachment_id) or {}

    @_synchronized
    def get_attachment(self, user_id, attachment_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, user_id, thread_id, original_filename, storage_key, "
                "mime_type, size_bytes, status, parser_type, parser_error, "
                "knowledge_document_id, created_at, last_used_at, expires_at "
                "FROM chat_attachments WHERE id=%s AND user_id=%s",
                (attachment_id, user_id),
            ).fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def list_attachments(self, user_id, thread_id) -> list[dict]:
        with self._connect() as conn, conn.transaction():
            rows = conn.execute(
                "SELECT id, user_id, thread_id, original_filename, storage_key, "
                "mime_type, size_bytes, status, parser_type, parser_error, "
                "knowledge_document_id, created_at, last_used_at, expires_at "
                "FROM chat_attachments WHERE thread_id=%s AND user_id=%s "
                "AND status != 'deleted' ORDER BY created_at, id",
                (thread_id, user_id),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    @_synchronized
    def update_status(self, user_id, attachment_id, status, parser_error=None,
                      parser_type=None, knowledge_document_id=None, last_used_at=None) -> dict:
        lu = last_used_at or _now()
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "UPDATE chat_attachments SET status=%s, parser_error=%s, parser_type=%s, "
                "knowledge_document_id=%s, last_used_at=%s WHERE id=%s AND user_id=%s",
                (status, parser_error, parser_type, knowledge_document_id, lu,
                 attachment_id, user_id),
            )
        return self.get_attachment(user_id, attachment_id) or {}

    @_synchronized
    def delete_attachment(self, user_id, attachment_id) -> bool:
        with self._connect() as conn, conn.transaction():
            cur = conn.execute(
                "DELETE FROM chat_attachments WHERE id=%s AND user_id=%s",
                (attachment_id, user_id),
            )
        return bool(cur.rowcount)

    @_synchronized
    def delete_all_for_user(self, user_id) -> list[dict]:
        """账号删除：删该用户全部附件行，返回被删行的 storage_key 列表（供磁盘清理）。"""
        with self._connect() as conn, conn.transaction():
            rows = conn.execute(
                "SELECT storage_key FROM chat_attachments WHERE user_id=%s",
                (user_id,),
            ).fetchall()
            conn.execute("DELETE FROM chat_attachments WHERE user_id=%s", (user_id,))
        return [r["storage_key"] for r in rows]

    @_synchronized
    def count_nondeleted(self, user_id, thread_id) -> int:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM chat_attachments "
                "WHERE thread_id=%s AND user_id=%s AND status != 'deleted'",
                (thread_id, user_id),
            ).fetchone()
        return int(row["n"])

    @_synchronized
    def clear_expires_at(self, user_id, attachment_id) -> dict:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "UPDATE chat_attachments SET expires_at=NULL, status='saved_to_knowledge', "
                "last_used_at=%s WHERE id=%s AND user_id=%s",
                (_now(), attachment_id, user_id),
            )
        return self.get_attachment(user_id, attachment_id) or {}

    @_synchronized
    def list_expired(self, now) -> list[dict]:
        with self._connect() as conn, conn.transaction():
            rows = conn.execute(
                "SELECT id, user_id, thread_id, original_filename, storage_key, "
                "mime_type, size_bytes, status, parser_type, parser_error, "
                "knowledge_document_id, created_at, last_used_at, expires_at "
                "FROM chat_attachments WHERE expires_at IS NOT NULL "
                "AND expires_at < %s AND status != 'saved_to_knowledge'",
                (now,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


class FakeAttachmentDb(AttachmentDb):
    """内存实现（单测用），语义与 PostgresAttachmentDb 对齐。"""

    def __init__(self) -> None:
        self.write_lock = threading.RLock()
        self._rows: dict[str, dict] = {}

    def create_attachment(self, attachment_id, user_id, thread_id, original_filename,
                          storage_key, mime_type, size_bytes, status, parser_type=None,
                          parser_error=None, knowledge_document_id=None, created_at=None,
                          last_used_at=None, expires_at=None) -> dict:
        now = created_at or _now()
        row = {
            "id": attachment_id, "user_id": user_id, "thread_id": thread_id,
            "original_filename": original_filename, "storage_key": storage_key,
            "mime_type": mime_type, "size_bytes": size_bytes, "status": status,
            "parser_type": parser_type, "parser_error": parser_error,
            "knowledge_document_id": knowledge_document_id,
            "created_at": now, "last_used_at": last_used_at or now,
            "expires_at": expires_at,
        }
        self._rows[attachment_id] = row
        return dict(row)

    def get_attachment(self, user_id, attachment_id) -> dict | None:
        row = self._rows.get(attachment_id)
        if row and row["user_id"] == user_id:
            return dict(row)
        return None

    def list_attachments(self, user_id, thread_id) -> list[dict]:
        rows = [r for r in self._rows.values()
                if r["thread_id"] == thread_id and r["user_id"] == user_id
                and r["status"] != "deleted"]
        rows.sort(key=lambda r: (r["created_at"], r["id"]))
        return [dict(r) for r in rows]

    def update_status(self, user_id, attachment_id, status, parser_error=None,
                      parser_type=None, knowledge_document_id=None, last_used_at=None) -> dict:
        row = self._rows.get(attachment_id)
        if row and row["user_id"] == user_id:
            row["status"] = status
            row["parser_error"] = parser_error
            if parser_type is not None:
                row["parser_type"] = parser_type
            if knowledge_document_id is not None:
                row["knowledge_document_id"] = knowledge_document_id
            row["last_used_at"] = last_used_at or _now()
            return dict(row)
        return {}

    def delete_attachment(self, user_id, attachment_id) -> bool:
        row = self._rows.get(attachment_id)
        if row and row["user_id"] == user_id:
            del self._rows[attachment_id]
            return True
        return False

    def delete_all_for_user(self, user_id) -> list[dict]:
        """账号删除：删该用户全部附件行，返回 storage_key 列表（供磁盘清理）。"""
        with self.write_lock:
            keys = [r["storage_key"] for r in self._rows.values() if r["user_id"] == user_id]
            for aid in [aid for aid, r in self._rows.items() if r["user_id"] == user_id]:
                del self._rows[aid]
            return keys

    def count_nondeleted(self, user_id, thread_id) -> int:
        return sum(
            1 for r in self._rows.values()
            if r["thread_id"] == thread_id and r["user_id"] == user_id
            and r["status"] != "deleted"
        )

    def clear_expires_at(self, user_id, attachment_id) -> dict:
        row = self._rows.get(attachment_id)
        if row and row["user_id"] == user_id:
            row["expires_at"] = None
            row["status"] = "saved_to_knowledge"
            row["last_used_at"] = _now()
            return dict(row)
        return {}

    def list_expired(self, now) -> list[dict]:
        return [
            dict(r) for r in self._rows.values()
            if r.get("expires_at") is not None
            and r["expires_at"] < now
            and r["status"] != "saved_to_knowledge"
        ]


class AttachmentStore:
    """附件领域服务：所有权校验 + 状态流转 + TTL；不直接碰磁盘（路由层负责落盘）。"""

    def __init__(self, db: AttachmentDb) -> None:
        self._db = db

    # ── create / read ──

    def create(self, thread_id: str, user_id: str, original_filename: str,
               storage_key: str, mime_type: str | None, size_bytes: int | None,
               status: str = "uploaded", expires_at: datetime | None = None,
               attachment_id: str | None = None) -> dict:
        """创建附件行（默认 uuid7 id，可显式传入 attachment_id 供路由落盘前复用）。

        expires_at 默认 now + 7d。
        """
        if attachment_id is None:
            attachment_id = str(uuid7())
        if expires_at is None:
            expires_at = _now() + timedelta(days=DEFAULT_TTL_DAYS)
        return self._db.create_attachment(
            attachment_id, user_id, thread_id, original_filename, storage_key,
            mime_type, size_bytes, status, expires_at=expires_at,
        )

    def get(self, user_id: str, attachment_id: str) -> dict:
        """取单个附件；跨用户 / 不存在 → OwnershipError。"""
        row = self._db.get_attachment(user_id, attachment_id)
        if row is None:
            raise OwnershipError(f"attachment {attachment_id!r} 不存在或不属于用户 {user_id!r}")
        return row

    def list_attachments(self, user_id: str, thread_id: str) -> list[dict]:
        return self._db.list_attachments(user_id, thread_id)

    def count_nondeleted(self, user_id: str, thread_id: str) -> int:
        return self._db.count_nondeleted(user_id, thread_id)

    def delete_all_for_user(self, user_id: str) -> list[dict]:
        """账号删除：删该用户全部附件行，返回 storage_key 列表（路由层负责磁盘清理）。"""
        return self._db.delete_all_for_user(user_id)

    # ── update / delete ──

    def update_status(self, user_id: str, attachment_id: str, status: str,
                      parser_error: str | None = None, parser_type: str | None = None,
                      knowledge_document_id: str | None = None) -> dict:
        if self._db.get_attachment(user_id, attachment_id) is None:
            raise OwnershipError(f"attachment {attachment_id!r} 不存在或不属于用户")
        return self._db.update_status(
            user_id, attachment_id, status, parser_error=parser_error,
            parser_type=parser_type, knowledge_document_id=knowledge_document_id,
        )

    def delete(self, user_id: str, attachment_id: str) -> bool:
        if self._db.get_attachment(user_id, attachment_id) is None:
            raise OwnershipError(f"attachment {attachment_id!r} 不存在或不属于用户")
        return self._db.delete_attachment(user_id, attachment_id)

    # ── TTL / save-to-knowledge ──

    def mark_saved(self, attachment_id: str, user_id: str,
                   knowledge_document_id: str | None = None) -> dict:
        """保存到知识库后取消 TTL（expires_at=NULL，status=saved_to_knowledge）。"""
        if self._db.get_attachment(user_id, attachment_id) is None:
            raise OwnershipError(f"attachment {attachment_id!r} 不存在或不属于用户")
        row = self._db.clear_expires_at(user_id, attachment_id)
        if knowledge_document_id:
            row = self._db.update_status(
                user_id, attachment_id, "saved_to_knowledge",
                knowledge_document_id=knowledge_document_id,
            )
        return row

    def expired_attachments(self, now: datetime | None = None) -> list[dict]:
        """返回已过期（expires_at < now）且未保存到知识库的附件行。"""
        ref = now or datetime.now(UTC)
        return self._db.list_expired(ref)


def create_attachment_db(settings) -> AttachmentDb:
    """按配置创建附件库：Postgres（生产）或 Fake（测试 backend=fake）。"""
    backend = getattr(settings.vector_store, "backend", "")
    dsn = (settings.memory.postgres.dsn or "").strip()
    if backend == "fake":
        return FakeAttachmentDb()
    if not dsn:
        raise ValueError("memory.postgres.dsn 未设置（生产环境附件库必须使用 Postgres）")
    return PostgresAttachmentDb(dsn)
