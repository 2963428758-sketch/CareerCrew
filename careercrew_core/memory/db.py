"""记忆统一持久化层：抽象接口 + Postgres 实现 + 内存 Fake。

三层记忆（情景事件 / 语义事实 / 治理策略）+ 会话线程元数据统一进一个
Postgres 库（生产）；FakeMemoryDb 供单测（与 BaseVectorStore/FakeVectorStore
同模式，测试不依赖真实 Postgres）。

所有行都带 user_id，替代旧实现里 u_001 硬编码。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from functools import wraps
import threading
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: Any) -> dict:
    """psycopg dict_row 行转普通 dict（复制一份，避免后续 mutate 影响连接）。"""
    return dict(row)


def _synchronized(fn):
    """PostgresMemoryDb 单连接非线程安全：所有公开方法串行化（RLock 可重入）。"""

    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self.write_lock:
            return fn(self, *args, **kwargs)

    return wrapper


class MemoryDb(ABC):
    """记忆持久化契约。"""

    # ── episodic ──

    @abstractmethod
    def insert_episodic(
        self,
        user_id: str,
        thread_id: str,
        entry_id: str,
        parent_id: str | None,
        type: str,
        content: dict | str,
        ts: str,
    ) -> dict: ...

    @abstractmethod
    def get_episodic(self, user_id: str, entry_id: str) -> dict | None: ...

    @abstractmethod
    def list_episodic(
        self,
        user_id: str,
        thread_id: str | None = None,
        type: str | None = None,
        limit: int | None = None,
    ) -> list[dict]: ...

    @abstractmethod
    def delete_episodic(
        self,
        user_id: str,
        entry_id: str | None = None,
        thread_id: str | None = None,
        type: str | None = None,
    ) -> int: ...

    @abstractmethod
    def latest_episodic(self, user_id: str, thread_id: str) -> dict | None: ...

    @abstractmethod
    def children_episodic(self, user_id: str, parent_id: str) -> list[dict]: ...

    @abstractmethod
    def chain_episodic(self, user_id: str, leaf_id: str) -> list[dict]: ...

    @abstractmethod
    def next_episodic_id(self, user_id: str) -> str: ...

    # ── semantic facts ──

    @abstractmethod
    def upsert_fact(
        self,
        user_id: str,
        name: str,
        type: str,
        description: str,
        content: dict,
        source: str,
        confidence: float,
    ) -> dict: ...

    @abstractmethod
    def get_fact(self, user_id: str, name: str) -> dict | None: ...

    @abstractmethod
    def list_facts(self, user_id: str, type: str | None = None) -> list[dict]: ...

    @abstractmethod
    def delete_fact(self, user_id: str, name: str | None = None, type: str | None = None) -> int: ...

    # ── policy（用户级 + 全局）──

    @abstractmethod
    def get_policy(self, user_id: str) -> dict: ...

    @abstractmethod
    def set_policy(self, user_id: str, enabled: bool, generate: bool, use: bool) -> dict: ...

    @abstractmethod
    def get_global_policy(self) -> dict: ...

    @abstractmethod
    def set_global_policy(self, enabled: bool, generate: bool, use: bool) -> dict: ...

    # ── threads ──

    @abstractmethod
    def upsert_thread(
        self,
        user_id: str,
        thread_id: str,
        title: str,
        module: str,
        pinned: bool,
    ) -> dict: ...

    @abstractmethod
    def get_thread(self, user_id: str, thread_id: str) -> dict | None: ...

    @abstractmethod
    def list_threads(self, user_id: str, module: str | None = None) -> list[dict]: ...

    @abstractmethod
    def delete_thread(self, user_id: str, thread_id: str) -> int: ...


class PostgresMemoryDb(MemoryDb):
    """Postgres 实现（psycopg 3）。连接惰性建立：首次操作才 connect + 建表。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn = None
        # 单 psycopg 连接被多个请求线程（并行会话）共用，psycopg 连接非线程安全；
        # RLock 保证同一线程内嵌套调用可重入，跨线程操作串行化。
        self.write_lock = threading.RLock()

    def _ensure(self):
        if self._conn is not None:
            return self._conn
        try:
            import psycopg
        except ImportError as e:  # pragma: no cover - env 缺依赖时给可读错误
            raise RuntimeError(
                "PostgresMemoryDb 需要 psycopg：pip install 'psycopg[binary]'"
            ) from e
        self._conn = psycopg.connect(self._dsn, row_factory=psycopg.rows.dict_row)
        self._conn.execute("CREATE TABLE IF NOT EXISTS episodic_events ("
                           "id TEXT NOT NULL, user_id TEXT NOT NULL, thread_id TEXT NOT NULL, "
                           "parent_id TEXT, type TEXT NOT NULL, content JSONB NOT NULL DEFAULT '{}'::jsonb, "
                           "ts TEXT NOT NULL, PRIMARY KEY (user_id, id))")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_episodic_user_thread "
                           "ON episodic_events(user_id, thread_id, ts)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_episodic_user_type "
                           "ON episodic_events(user_id, type)")
        self._conn.execute("CREATE TABLE IF NOT EXISTS semantic_facts ("
                           "user_id TEXT NOT NULL, name TEXT NOT NULL, type TEXT NOT NULL, "
                           "description TEXT NOT NULL DEFAULT '', content JSONB NOT NULL DEFAULT '{}'::jsonb, "
                           "source TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL DEFAULT 1.0, "
                           "version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, "
                           "modified_at TEXT NOT NULL, PRIMARY KEY (user_id, name))")
        self._conn.execute("CREATE TABLE IF NOT EXISTS user_memory_policy ("
                           "user_id TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT false, "
                           "generate BOOLEAN NOT NULL DEFAULT true, use BOOLEAN NOT NULL DEFAULT true, "
                           "updated_at TEXT NOT NULL)")
        self._conn.execute("CREATE TABLE IF NOT EXISTS memory_global_policy ("
                           "id INTEGER PRIMARY KEY CHECK (id = 1), "
                           "enabled BOOLEAN NOT NULL DEFAULT false, "
                           "generate BOOLEAN NOT NULL DEFAULT true, use BOOLEAN NOT NULL DEFAULT true, "
                           "updated_at TEXT NOT NULL)")
        self._conn.execute("CREATE TABLE IF NOT EXISTS threads ("
                           "user_id TEXT NOT NULL, thread_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', "
                           "module TEXT NOT NULL DEFAULT 'chat', pinned BOOLEAN NOT NULL DEFAULT false, "
                           "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
                           "PRIMARY KEY (user_id, thread_id))")
        # 会话检索范围（知识库分类等）元数据；历史行回退 NULL（前端视为"全部"）。
        # 目录守卫 + 短锁超时：避免在并发连接持有 threads 事务时被 ALTER 永久阻塞。
        self._conn.execute("SET lock_timeout = '5s'")
        try:
            self._conn.execute(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'threads' AND column_name = 'retrieval_scope') THEN "
                "ALTER TABLE threads ADD COLUMN retrieval_scope JSONB; "
                "END IF; END $$"
            )
        finally:
            self._conn.execute("SET lock_timeout = '0'")
        self._conn.commit()
        return self._conn

    # ── episodic ──

    @_synchronized
    def insert_episodic(self, user_id, thread_id, entry_id, parent_id, type, content, ts) -> dict:
        conn = self._ensure()
        conn.execute(
            "INSERT INTO episodic_events (id, user_id, thread_id, parent_id, type, content, ts) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s) "
            "ON CONFLICT (user_id, id) DO UPDATE SET parent_id=EXCLUDED.parent_id, "
            "type=EXCLUDED.type, content=EXCLUDED.content, ts=EXCLUDED.ts, "
            "thread_id=EXCLUDED.thread_id",
            (entry_id, user_id, thread_id, parent_id, type, _json_dumps(content), ts),
        )
        conn.commit()
        return self.get_episodic(user_id, entry_id) or {}

    @_synchronized
    def get_episodic(self, user_id, entry_id) -> dict | None:
        conn = self._ensure()
        cur = conn.execute(
            "SELECT id, user_id, thread_id, parent_id, type, content, ts FROM episodic_events "
            "WHERE user_id=%s AND id=%s",
            (user_id, entry_id),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def list_episodic(self, user_id, thread_id=None, type=None, limit=None) -> list[dict]:
        conn = self._ensure()
        sql = "SELECT id, user_id, thread_id, parent_id, type, content, ts FROM episodic_events WHERE user_id=%s"
        params: list = [user_id]
        if thread_id:
            sql += " AND thread_id=%s"
            params.append(thread_id)
        if type:
            sql += " AND type=%s"
            params.append(type)
        sql += " ORDER BY ts, id"
        if limit:
            sql += " LIMIT %s"
            params.append(limit)
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [_row_to_dict(r) for r in rows]

    @_synchronized
    def delete_episodic(self, user_id, entry_id=None, thread_id=None, type=None) -> int:
        conn = self._ensure()
        sql = "DELETE FROM episodic_events WHERE user_id=%s"
        params: list = [user_id]
        if entry_id:
            sql += " AND id=%s"
            params.append(entry_id)
        if thread_id:
            sql += " AND thread_id=%s"
            params.append(thread_id)
        if type:
            sql += " AND type=%s"
            params.append(type)
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.rowcount or 0

    @_synchronized
    def latest_episodic(self, user_id, thread_id) -> dict | None:
        conn = self._ensure()
        row = conn.execute(
            "SELECT id, user_id, thread_id, parent_id, type, content, ts FROM episodic_events "
            "WHERE user_id=%s AND thread_id=%s ORDER BY ts DESC, id DESC LIMIT 1",
            (user_id, thread_id),
        ).fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def children_episodic(self, user_id, parent_id) -> list[dict]:
        conn = self._ensure()
        rows = conn.execute(
            "SELECT id, user_id, thread_id, parent_id, type, content, ts FROM episodic_events "
            "WHERE user_id=%s AND parent_id=%s ORDER BY ts, id",
            (user_id, parent_id),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    @_synchronized
    def chain_episodic(self, user_id, leaf_id) -> list[dict]:
        """从叶子沿 parent_id 回溯到根，返回 root -> leaf（用应用层遍历，量小）。"""
        conn = self._ensure()
        rows = conn.execute(
            "SELECT id, user_id, thread_id, parent_id, type, content, ts FROM episodic_events "
            "WHERE user_id=%s",
            (user_id,),
        ).fetchall()
        by_id = {r["id"]: r for r in rows}
        chain: list[dict] = []
        cur = by_id.get(leaf_id)
        seen: set[str] = set()
        while cur and cur["id"] not in seen:
            chain.append(cur)
            seen.add(cur["id"])
            cur = by_id.get(cur["parent_id"]) if cur.get("parent_id") else None
        return list(reversed(chain))

    @_synchronized
    def next_episodic_id(self, user_id) -> str:
        conn = self._ensure()
        # 用 MAX(id) 而不是 COUNT(*)：删除历史行后 COUNT 会回退，导致 id 重用、
        # ON CONFLICT 覆盖旧行（thread_id 串线程）。MAX 保证单调不复用。
        row = conn.execute(
            "SELECT COALESCE(MAX((substring(id from 3))::int), 0) AS n "
            "FROM episodic_events WHERE user_id=%s AND id ~ '^e_[0-9]+$'",
            (user_id,),
        ).fetchone()
        return f"e_{int(row['n']) + 1:03d}"

    # ── semantic facts ──

    @_synchronized
    def upsert_fact(self, user_id, name, type, description, content, source, confidence) -> dict:
        conn = self._ensure()
        now = _now()
        existing = self.get_fact(user_id, name)
        version = (existing.get("version") or 0) + 1 if existing else 1
        created_at = (existing or {}).get("created_at") or now
        conn.execute(
            "INSERT INTO semantic_facts (user_id, name, type, description, content, source, confidence, "
            "version, created_at, modified_at) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, name) DO UPDATE SET type=EXCLUDED.type, description=EXCLUDED.description, "
            "content=EXCLUDED.content, source=EXCLUDED.source, confidence=EXCLUDED.confidence, "
            "version=EXCLUDED.version, modified_at=EXCLUDED.modified_at",
            (user_id, name, type, description, _json_dumps(content), source, confidence,
             version, created_at, now),
        )
        conn.commit()
        return self.get_fact(user_id, name) or {}

    @_synchronized
    def get_fact(self, user_id, name) -> dict | None:
        conn = self._ensure()
        row = conn.execute(
            "SELECT user_id, name, type, description, content, source, confidence, version, "
            "created_at, modified_at FROM semantic_facts WHERE user_id=%s AND name=%s",
            (user_id, name),
        ).fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def list_facts(self, user_id, type=None) -> list[dict]:
        conn = self._ensure()
        if type:
            rows = conn.execute(
                "SELECT user_id, name, type, description, content, source, confidence, version, "
                "created_at, modified_at FROM semantic_facts WHERE user_id=%s AND type=%s "
                "ORDER BY modified_at DESC",
                (user_id, type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT user_id, name, type, description, content, source, confidence, version, "
                "created_at, modified_at FROM semantic_facts WHERE user_id=%s ORDER BY modified_at DESC",
                (user_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    @_synchronized
    def delete_fact(self, user_id, name=None, type=None) -> int:
        conn = self._ensure()
        sql = "DELETE FROM semantic_facts WHERE user_id=%s"
        params: list = [user_id]
        if name:
            sql += " AND name=%s"
            params.append(name)
        if type:
            sql += " AND type=%s"
            params.append(type)
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.rowcount or 0

    # ── policy ──

    @_synchronized
    def get_policy(self, user_id) -> dict:
        conn = self._ensure()
        row = conn.execute(
            "SELECT user_id, enabled, generate, use, updated_at FROM user_memory_policy WHERE user_id=%s",
            (user_id,),
        ).fetchone()
        if row:
            return _row_to_dict(row)
        return {"user_id": user_id, "enabled": False, "generate": True, "use": True, "updated_at": _now()}

    @_synchronized
    def set_policy(self, user_id, enabled, generate, use) -> dict:
        conn = self._ensure()
        now = _now()
        conn.execute(
            "INSERT INTO user_memory_policy (user_id, enabled, generate, use, updated_at) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET enabled=EXCLUDED.enabled, "
            "generate=EXCLUDED.generate, use=EXCLUDED.use, updated_at=EXCLUDED.updated_at",
            (user_id, bool(enabled), bool(generate), bool(use), now),
        )
        conn.commit()
        return self.get_policy(user_id)

    @_synchronized
    def get_global_policy(self) -> dict:
        conn = self._ensure()
        row = conn.execute(
            "SELECT id, enabled, generate, use, updated_at FROM memory_global_policy WHERE id=1"
        ).fetchone()
        if row:
            return _row_to_dict(row)
        return {"id": 1, "enabled": False, "generate": True, "use": True, "updated_at": _now()}

    @_synchronized
    def set_global_policy(self, enabled, generate, use) -> dict:
        conn = self._ensure()
        now = _now()
        conn.execute(
            "INSERT INTO memory_global_policy (id, enabled, generate, use, updated_at) "
            "VALUES (1, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET enabled=EXCLUDED.enabled, "
            "generate=EXCLUDED.generate, use=EXCLUDED.use, updated_at=EXCLUDED.updated_at",
            (bool(enabled), bool(generate), bool(use), now),
        )
        conn.commit()
        return self.get_global_policy()

    # ── threads ──

    @_synchronized
    def upsert_thread(self, user_id, thread_id, title, module, pinned, retrieval_scope=None) -> dict:
        conn = self._ensure()
        now = _now()
        existing = self.get_thread(user_id, thread_id)
        created_at = existing.get("created_at") or now if existing else now
        conn.execute(
            "INSERT INTO threads (user_id, thread_id, title, module, pinned, retrieval_scope, "
            "created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s) "
            "ON CONFLICT (user_id, thread_id) DO UPDATE SET "
            "title=EXCLUDED.title, module=EXCLUDED.module, pinned=EXCLUDED.pinned, "
            "retrieval_scope=COALESCE(EXCLUDED.retrieval_scope, threads.retrieval_scope), "
            "updated_at=EXCLUDED.updated_at",
            (user_id, thread_id, title or "", module or "chat", bool(pinned),
             _json_dumps(retrieval_scope) if retrieval_scope is not None else None,
             created_at, now),
        )
        conn.commit()
        return self.get_thread(user_id, thread_id) or {}

    @_synchronized
    def get_thread(self, user_id, thread_id) -> dict | None:
        conn = self._ensure()
        row = conn.execute(
            "SELECT user_id, thread_id, title, module, pinned, retrieval_scope, created_at, updated_at "
            "FROM threads WHERE user_id=%s AND thread_id=%s",
            (user_id, thread_id),
        ).fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def list_threads(self, user_id, module=None) -> list[dict]:
        conn = self._ensure()
        cols = "user_id, thread_id, title, module, pinned, retrieval_scope, created_at, updated_at"
        if module:
            rows = conn.execute(
                f"SELECT {cols} FROM threads WHERE user_id=%s AND module=%s "
                "ORDER BY pinned DESC, updated_at DESC",
                (user_id, module),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {cols} FROM threads WHERE user_id=%s ORDER BY pinned DESC, updated_at DESC",
                (user_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    @_synchronized
    def delete_thread(self, user_id, thread_id) -> int:
        conn = self._ensure()
        cur = conn.execute(
            "DELETE FROM threads WHERE user_id=%s AND thread_id=%s", (user_id, thread_id)
        )
        conn.commit()
        return cur.rowcount or 0


class FakeMemoryDb(MemoryDb):
    """内存实现（单测用），接口与 PostgresMemoryDb 一致。"""

    def __init__(self) -> None:
        self.write_lock = threading.RLock()
        self._episodic: dict[tuple[str, str], dict] = {}
        self._facts: dict[tuple[str, str], dict] = {}
        self._policies: dict[str, dict] = {}
        self._global_policy: dict = {"id": 1, "enabled": False, "generate": True, "use": True, "updated_at": _now()}
        self._threads: dict[tuple[str, str], dict] = {}

    def insert_episodic(self, user_id, thread_id, entry_id, parent_id, type, content, ts) -> dict:
        row = {
            "id": entry_id, "user_id": user_id, "thread_id": thread_id, "parent_id": parent_id,
            "type": type, "content": content, "ts": ts,
        }
        self._episodic[(user_id, entry_id)] = row
        return dict(row)

    def get_episodic(self, user_id, entry_id) -> dict | None:
        row = self._episodic.get((user_id, entry_id))
        return dict(row) if row else None

    def list_episodic(self, user_id, thread_id=None, type=None, limit=None) -> list[dict]:
        rows = [r for (u, _), r in self._episodic.items() if u == user_id]
        if thread_id:
            rows = [r for r in rows if r["thread_id"] == thread_id]
        if type:
            rows = [r for r in rows if r["type"] == type]
        rows.sort(key=lambda r: (r["ts"], r["id"]))
        if limit:
            rows = rows[:limit]
        return [dict(r) for r in rows]

    def delete_episodic(self, user_id, entry_id=None, thread_id=None, type=None) -> int:
        to_del = [
            k for k in list(self._episodic)
            if k[0] == user_id
            and (entry_id is None or k[1] == entry_id)
            and (thread_id is None or self._episodic[k]["thread_id"] == thread_id)
            and (type is None or self._episodic[k]["type"] == type)
        ]
        for k in to_del:
            del self._episodic[k]
        return len(to_del)

    def latest_episodic(self, user_id, thread_id) -> dict | None:
        rows = self.list_episodic(user_id, thread_id=thread_id)
        return dict(rows[-1]) if rows else None

    def children_episodic(self, user_id, parent_id) -> list[dict]:
        rows = [r for r in self.list_episodic(user_id) if r["parent_id"] == parent_id]
        rows.sort(key=lambda r: (r["ts"], r["id"]))
        return [dict(r) for r in rows]

    def chain_episodic(self, user_id, leaf_id) -> list[dict]:
        by_id = {r["id"]: r for r in self.list_episodic(user_id)}
        chain: list[dict] = []
        cur = by_id.get(leaf_id)
        seen: set[str] = set()
        while cur and cur["id"] not in seen:
            chain.append(cur)
            seen.add(cur["id"])
            cur = by_id.get(cur["parent_id"]) if cur.get("parent_id") else None
        return [dict(r) for r in reversed(chain)]

    def next_episodic_id(self, user_id) -> str:
        nums = [
            int(k.split("_", 1)[1])
            for (u, k) in self._episodic
            if u == user_id and k.startswith("e_") and k[2:].isdigit()
        ]
        return f"e_{max(nums, default=0) + 1:03d}"

    def upsert_fact(self, user_id, name, type, description, content, source, confidence) -> dict:
        now = _now()
        existing = self.get_fact(user_id, name)
        version = (existing.get("version") or 0) + 1 if existing else 1
        created_at = (existing or {}).get("created_at") or now
        row = {
            "user_id": user_id, "name": name, "type": type, "description": description,
            "content": content, "source": source, "confidence": float(confidence),
            "version": version, "created_at": created_at, "modified_at": now,
        }
        self._facts[(user_id, name)] = row
        return dict(row)

    def get_fact(self, user_id, name) -> dict | None:
        row = self._facts.get((user_id, name))
        return dict(row) if row else None

    def list_facts(self, user_id, type=None) -> list[dict]:
        rows = [r for (u, _), r in self._facts.items() if u == user_id]
        if type:
            rows = [r for r in rows if r["type"] == type]
        rows.sort(key=lambda r: r["modified_at"], reverse=True)
        return [dict(r) for r in rows]

    def delete_fact(self, user_id, name=None, type=None) -> int:
        to_del = [
            k for k in list(self._facts)
            if k[0] == user_id
            and (name is None or k[1] == name)
            and (type is None or self._facts[k]["type"] == type)
        ]
        for k in to_del:
            del self._facts[k]
        return len(to_del)

    def get_policy(self, user_id) -> dict:
        row = self._policies.get(user_id)
        if row:
            return dict(row)
        return {"user_id": user_id, "enabled": False, "generate": True, "use": True, "updated_at": _now()}

    def set_policy(self, user_id, enabled, generate, use) -> dict:
        row = {
            "user_id": user_id, "enabled": bool(enabled), "generate": bool(generate),
            "use": bool(use), "updated_at": _now(),
        }
        self._policies[user_id] = row
        return dict(row)

    def get_global_policy(self) -> dict:
        return dict(self._global_policy)

    def set_global_policy(self, enabled, generate, use) -> dict:
        self._global_policy = {
            "id": 1, "enabled": bool(enabled), "generate": bool(generate),
            "use": bool(use), "updated_at": _now(),
        }
        return dict(self._global_policy)

    def upsert_thread(self, user_id, thread_id, title, module, pinned, retrieval_scope=None) -> dict:
        now = _now()
        existing = self.get_thread(user_id, thread_id)
        created_at = existing.get("created_at") or now if existing else now
        row = {
            "user_id": user_id, "thread_id": thread_id, "title": title or "",
            "module": module or "chat", "pinned": bool(pinned),
            "retrieval_scope": retrieval_scope if retrieval_scope is not None
            else (existing or {}).get("retrieval_scope"),
            "created_at": created_at, "updated_at": now,
        }
        self._threads[(user_id, thread_id)] = row
        return dict(row)

    def get_thread(self, user_id, thread_id) -> dict | None:
        row = self._threads.get((user_id, thread_id))
        return dict(row) if row else None

    def list_threads(self, user_id, module=None) -> list[dict]:
        rows = [r for (u, _), r in self._threads.items() if u == user_id]
        if module:
            rows = [r for r in rows if r["module"] == module]
        rows.sort(key=lambda r: (not r["pinned"], r["updated_at"]), reverse=True)
        return [dict(r) for r in rows]

    def delete_thread(self, user_id, thread_id) -> int:
        if (user_id, thread_id) in self._threads:
            del self._threads[(user_id, thread_id)]
            return 1
        return 0


def create_memory_db(settings) -> MemoryDb:
    """按配置创建记忆库：Postgres（生产）或 Fake（测试后端 fake/postgres 缺 dsn 时）。"""
    backend = getattr(settings.vector_store, "backend", "")  # 测试常用 fake
    dsn = (settings.memory.postgres.dsn or "").strip()
    if backend == "fake" or not dsn:
        return FakeMemoryDb()
    return PostgresMemoryDb(dsn)


def _json_dumps(content: dict | str) -> str:
    import json

    if isinstance(content, str):
        return json.dumps({"text": content}, ensure_ascii=False)
    return json.dumps(content, ensure_ascii=False)
