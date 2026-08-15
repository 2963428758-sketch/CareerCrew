"""对话核心持久化层：抽象接口 + Postgres 实现 + 内存 Fake。

conversations / conversation_turns / messages / agent_runs /
agent_run_retrievals / agent_run_tool_calls 六张表统一进 Postgres（生产）；
FakeConversationDb 供单测（与 FakeMemoryDb 同模式，测试不依赖真实 Postgres）。

风格对齐 careercrew_core/memory/db.py：CREATE TABLE IF NOT EXISTS +
ALTER TABLE ADD COLUMN IF NOT EXISTS 幂等迁移、psycopg dict_row、
事务 `with self._connect() as conn, conn.transaction():`、_iso 时间戳。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from functools import wraps
import threading
from typing import Any
from uuid import UUID

from careercrew_core.conversation.uuid7 import uuid7


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SequenceCollision(Exception):
    """turn 插入时 UNIQUE(thread_id, sequence_no) 冲突归一化信号。

    两实现（Postgres / Fake）在撞车时都抛此类型，store 层据此重试一次，
    其余异常原样上抛，不吞掉非唯一冲突的故障。
    """


def _is_unique_violation(err: BaseException) -> bool:
    """识别唯一约束冲突：psycopg 的 UniqueViolation（SQLSTATE 23505）。

    用类型名匹配，避免强绑定 psycopg.errors 模块路径（同 auth/store.py）。
    """
    return type(err).__name__ == "UniqueViolation" or getattr(
        err, "sqlstate", None
    ) == "23505"


def _row_to_dict(row: Any) -> dict:
    """psycopg dict_row 行转普通 dict（复制一份，UUID 归一为 str，避免 mutate 影响连接）。"""
    return {k: (str(v) if isinstance(v, UUID) else v) for k, v in dict(row).items()}


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _synchronized(fn):
    """PostgresConversationDb 单连接非线程安全：所有公开方法串行化（RLock 可重入）。"""

    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self.write_lock:
            return fn(self, *args, **kwargs)

    return wrapper


class ConversationDb(ABC):
    """对话核心持久化契约。"""

    # ── conversations ──

    @abstractmethod
    def upsert_conversation(
        self,
        conversation_id: str,
        user_id: str,
        module: str,
        title: str | None,
        legacy_thread_id: str | None,
        retrieval_scope: dict | None = None,
    ) -> dict: ...

    @abstractmethod
    def get_conversation(self, user_id: str, conversation_id: str) -> dict | None: ...

    @abstractmethod
    def get_conversation_by_legacy(self, user_id: str, legacy_thread_id: str) -> dict | None: ...

    @abstractmethod
    def conversation_exists(self, conversation_id: str) -> bool: ...

    @abstractmethod
    def legacy_exists(self, legacy_thread_id: str) -> bool: ...

    # ── turns ──

    @abstractmethod
    def insert_turn(
        self, turn_id: str, thread_id: str, user_id: str, sequence_no: int
    ) -> dict: ...

    @abstractmethod
    def max_sequence_no(self, user_id: str, thread_id: str) -> int: ...

    @abstractmethod
    def get_turn(self, user_id: str, turn_id: str) -> dict | None: ...

    # ── messages ──

    @abstractmethod
    def insert_message(
        self,
        message_id: str,
        thread_id: str,
        turn_id: str,
        user_id: str,
        role: str,
        content: str,
        run_id: str | None,
        regenerated_from_message_id: str | None,
        status: str,
    ) -> dict: ...

    @abstractmethod
    def get_message(self, user_id: str, message_id: str) -> dict | None: ...

    @abstractmethod
    def update_message_status(self, user_id: str, message_id: str, status: str) -> dict: ...

    @abstractmethod
    def list_messages(self, user_id: str, thread_id: str) -> list[dict]: ...

    # ── runs ──

    @abstractmethod
    def insert_run(self, run_id: str, user_id: str, thread_id: str, turn_id: str,
                   message_id: str, module: str, agent_id: str, model: str,
                   prompt_version: str, agent_version: str, status: str) -> dict: ...

    @abstractmethod
    def get_run(self, user_id: str, run_id: str) -> dict | None: ...

    @abstractmethod
    def update_run(self, user_id: str, run_id: str, fields: dict) -> dict: ...

    # ── retrievals / tool calls ──

    @abstractmethod
    def insert_retrieval(self, retrieval_id: str, run_id: str, query_index: int,
                         fields: dict) -> dict: ...

    @abstractmethod
    def insert_tool_call(self, tool_call_id: str, run_id: str, tool_name: str,
                         fields: dict) -> dict: ...


class PostgresConversationDb(ConversationDb):
    """Postgres 实现（psycopg 3）。连接惰性建立：首次操作才 connect + 建表。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connected = False
        self.write_lock = threading.RLock()

    def _connect(self):
        if not self._connected:
            self._ensure()
        import psycopg

        return psycopg.connect(self._dsn, row_factory=psycopg.rows.dict_row)

    @_synchronized
    def _ensure(self):
        """首次操作时惰性建表（幂等：CREATE IF NOT EXISTS + ADD COLUMN IF NOT EXISTS）。"""
        if self._connected:
            return
        try:
            import psycopg
        except ImportError as e:  # pragma: no cover - env 缺依赖时给可读错误
            raise RuntimeError(
                "PostgresConversationDb 需要 psycopg：pip install 'psycopg[binary]'"
            ) from e
        with psycopg.connect(self._dsn, row_factory=psycopg.rows.dict_row) as conn, conn.transaction():
            conn.execute(
                "CREATE TABLE IF NOT EXISTS conversations ("
                "id UUID PRIMARY KEY, user_id VARCHAR(64) NOT NULL, module VARCHAR(50) NOT NULL, "
                "title VARCHAR(255), retrieval_scope JSONB, "
                "created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, "
                "last_active_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_user_updated "
                "ON conversations(user_id, updated_at DESC)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS conversation_turns ("
                "id UUID PRIMARY KEY, thread_id UUID NOT NULL REFERENCES conversations(id), "
                "user_id VARCHAR(64) NOT NULL, sequence_no INTEGER NOT NULL, "
                "created_at TIMESTAMPTZ NOT NULL, UNIQUE(thread_id, sequence_no))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                "id UUID PRIMARY KEY, thread_id UUID NOT NULL, turn_id UUID NOT NULL, "
                "user_id VARCHAR(64) NOT NULL, role VARCHAR(20) NOT NULL, content TEXT NOT NULL, "
                "run_id UUID, regenerated_from_message_id UUID, status VARCHAR(20) NOT NULL, "
                "created_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ, deleted_at TIMESTAMPTZ)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agent_runs ("
                "id UUID PRIMARY KEY, user_id VARCHAR(64) NOT NULL, thread_id UUID NOT NULL, "
                "turn_id UUID NOT NULL, message_id UUID NOT NULL, "
                "module VARCHAR(50) NOT NULL, agent_id VARCHAR(100) NOT NULL, "
                "model VARCHAR(150) NOT NULL, prompt_version VARCHAR(80) NOT NULL, "
                "agent_version VARCHAR(80) NOT NULL, status VARCHAR(30) NOT NULL, "
                "input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, "
                "latency_ms INTEGER, langsmith_run_id VARCHAR(255), "
                "error_type VARCHAR(100), error_code VARCHAR(100), error_summary TEXT, "
                "started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ, "
                "created_at TIMESTAMPTZ NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agent_run_retrievals ("
                "id UUID PRIMARY KEY, run_id UUID NOT NULL, query_index INTEGER NOT NULL, "
                "query_text_redacted TEXT, scope VARCHAR(50), document_id VARCHAR(255), "
                "chunk_id VARCHAR(255), recall_score DOUBLE PRECISION, "
                "rerank_score DOUBLE PRECISION, rank_before INTEGER, rank_after INTEGER, "
                "used_in_final_context BOOLEAN NOT NULL DEFAULT FALSE, "
                "created_at TIMESTAMPTZ NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agent_run_tool_calls ("
                "id UUID PRIMARY KEY, run_id UUID NOT NULL, tool_name VARCHAR(150) NOT NULL, "
                "input_redacted JSONB, output_summary TEXT, status VARCHAR(30) NOT NULL, "
                "duration_ms INTEGER, requires_hitl BOOLEAN NOT NULL DEFAULT FALSE, "
                "hitl_status VARCHAR(30), error_type VARCHAR(100), error_summary TEXT, "
                "started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, "
                "created_at TIMESTAMPTZ NOT NULL)"
            )
            # legacy thread_id 映射（现状：前端用 `t-${Date.now()}` 非 UUID 线程 ID）。
            # 追加在方案 DDL 之后、幂等迁移添加；历史行回退 NULL。
            conn.execute("SET lock_timeout = '5s'")
            try:
                conn.execute(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'conversations' AND column_name = 'legacy_thread_id') THEN "
                    "ALTER TABLE conversations ADD COLUMN legacy_thread_id VARCHAR(255); "
                    "END IF; END $$"
                )
            finally:
                conn.execute("SET lock_timeout = '0'")
            conn.execute(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = "
                "'idx_conversations_legacy_thread_id') THEN "
                "CREATE UNIQUE INDEX idx_conversations_legacy_thread_id "
                "ON conversations(legacy_thread_id) WHERE legacy_thread_id IS NOT NULL; "
                "END IF; END $$"
            )
        self._connected = True

    # ── conversations ──

    @_synchronized
    def upsert_conversation(self, conversation_id, user_id, module, title, legacy_thread_id,
                            retrieval_scope=None) -> dict:
        with self._connect() as conn, conn.transaction():
            now = _now()
            conn.execute(
                "INSERT INTO conversations (id, user_id, module, title, legacy_thread_id, "
                "retrieval_scope, created_at, updated_at, last_active_at) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET "
                "title=EXCLUDED.title, module=EXCLUDED.module, "
                "legacy_thread_id=COALESCE(EXCLUDED.legacy_thread_id, conversations.legacy_thread_id), "
                "retrieval_scope=COALESCE(EXCLUDED.retrieval_scope, conversations.retrieval_scope), "
                "updated_at=EXCLUDED.updated_at, last_active_at=EXCLUDED.last_active_at",
                (conversation_id, user_id, module, title, legacy_thread_id,
                 _json_dumps(retrieval_scope) if retrieval_scope is not None else None,
                 now, now, now),
            )
        return self.get_conversation(user_id, conversation_id) or {}

    @_synchronized
    def get_conversation(self, user_id, conversation_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, user_id, module, title, retrieval_scope, legacy_thread_id, "
                "created_at, updated_at, last_active_at, deleted_at FROM conversations "
                "WHERE id=%s AND user_id=%s",
                (conversation_id, user_id),
            ).fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def get_conversation_by_legacy(self, user_id, legacy_thread_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, user_id, module, title, retrieval_scope, legacy_thread_id, "
                "created_at, updated_at, last_active_at, deleted_at FROM conversations "
                "WHERE legacy_thread_id=%s AND user_id=%s",
                (legacy_thread_id, user_id),
            ).fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def conversation_exists(self, conversation_id) -> bool:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT 1 FROM conversations WHERE id=%s", (conversation_id,)
            ).fetchone()
        return row is not None

    @_synchronized
    def legacy_exists(self, legacy_thread_id) -> bool:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT 1 FROM conversations WHERE legacy_thread_id=%s",
                (legacy_thread_id,),
            ).fetchone()
        return row is not None

    # ── turns ──

    @_synchronized
    def insert_turn(self, turn_id, thread_id, user_id, sequence_no) -> dict:
        with self._connect() as conn, conn.transaction():
            try:
                conn.execute(
                    "INSERT INTO conversation_turns (id, thread_id, user_id, sequence_no, created_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (turn_id, thread_id, user_id, sequence_no, _now()),
                )
            except Exception as err:
                if _is_unique_violation(err):
                    raise SequenceCollision(
                        f"turn sequence {sequence_no} already exists for thread {thread_id}"
                    ) from err
                raise
        return self.get_turn(user_id, turn_id) or {}

    @_synchronized
    def max_sequence_no(self, user_id, thread_id) -> int:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT COALESCE(MAX(sequence_no), 0) AS n FROM conversation_turns "
                "WHERE thread_id=%s AND user_id=%s",
                (thread_id, user_id),
            ).fetchone()
        return int(row["n"])

    @_synchronized
    def get_turn(self, user_id, turn_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, thread_id, user_id, sequence_no, created_at "
                "FROM conversation_turns WHERE id=%s AND user_id=%s",
                (turn_id, user_id),
            ).fetchone()
        return _row_to_dict(row) if row else None

    # ── messages ──

    @_synchronized
    def insert_message(self, message_id, thread_id, turn_id, user_id, role, content,
                       run_id, regenerated_from_message_id, status) -> dict:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO messages (id, thread_id, turn_id, user_id, role, content, "
                "run_id, regenerated_from_message_id, status, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (message_id, thread_id, turn_id, user_id, role, content, run_id,
                 regenerated_from_message_id, status, _now()),
            )
        return self.get_message(user_id, message_id) or {}

    @_synchronized
    def get_message(self, user_id, message_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, thread_id, turn_id, user_id, role, content, run_id, "
                "regenerated_from_message_id, status, created_at, completed_at, deleted_at "
                "FROM messages WHERE id=%s AND user_id=%s",
                (message_id, user_id),
            ).fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def update_message_status(self, user_id, message_id, status) -> dict:
        with self._connect() as conn, conn.transaction():
            completed_at = _now() if status == "completed" else None
            conn.execute(
                "UPDATE messages SET status=%s, completed_at=%s "
                "WHERE id=%s AND user_id=%s",
                (status, completed_at, message_id, user_id),
            )
        row = None
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, thread_id, turn_id, user_id, role, content, run_id, "
                "regenerated_from_message_id, status, created_at, completed_at, deleted_at "
                "FROM messages WHERE id=%s AND user_id=%s",
                (message_id, user_id),
            ).fetchone()
        return _row_to_dict(row) if row else {}

    @_synchronized
    def list_messages(self, user_id, thread_id) -> list[dict]:
        with self._connect() as conn, conn.transaction():
            rows = conn.execute(
                "SELECT m.id, m.thread_id, m.turn_id, m.user_id, m.role, m.content, "
                "m.run_id, m.regenerated_from_message_id, m.status, m.created_at, "
                "m.completed_at, m.deleted_at "
                "FROM messages m "
                "JOIN conversation_turns t ON t.id = m.turn_id "
                "WHERE m.thread_id=%s AND m.user_id=%s "
                "ORDER BY t.sequence_no, m.created_at, m.id",
                (thread_id, user_id),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # ── runs ──

    @_synchronized
    def insert_run(self, run_id, user_id, thread_id, turn_id, message_id, module,
                   agent_id, model, prompt_version, agent_version, status) -> dict:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO agent_runs (id, user_id, thread_id, turn_id, message_id, "
                "module, agent_id, model, prompt_version, agent_version, status, "
                "started_at, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (run_id, user_id, thread_id, turn_id, message_id, module, agent_id,
                 model, prompt_version, agent_version, status, _now(), _now()),
            )
        return self.get_run(user_id, run_id) or {}

    @_synchronized
    def get_run(self, user_id, run_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, user_id, thread_id, turn_id, message_id, module, agent_id, "
                "model, prompt_version, agent_version, status, input_tokens, "
                "output_tokens, total_tokens, latency_ms, langsmith_run_id, error_type, "
                "error_code, error_summary, started_at, finished_at, created_at "
                "FROM agent_runs WHERE id=%s AND user_id=%s",
                (run_id, user_id),
            ).fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def update_run(self, user_id, run_id, fields) -> dict:
        with self._connect() as conn, conn.transaction():
            cols = list(fields.keys())
            if not cols:
                return self.get_run(user_id, run_id) or {}
            set_clause = ", ".join(f"{c}=%s" for c in cols)
            params = [fields[c] for c in cols] + [run_id, user_id]
            conn.execute(
                f"UPDATE agent_runs SET {set_clause} WHERE id=%s AND user_id=%s",
                tuple(params),
            )
        return self.get_run(user_id, run_id) or {}

    # ── retrievals / tool calls ──

    @_synchronized
    def insert_retrieval(self, retrieval_id, run_id, query_index, fields) -> dict:
        with self._connect() as conn, conn.transaction():
            cols = ["id", "run_id", "query_index"] + [c for c in fields if c != "created_at"]
            vals = [retrieval_id, run_id, query_index] + [
                fields[c] for c in fields if c != "created_at"
            ]
            conn.execute(
                f"INSERT INTO agent_run_retrievals ({', '.join(cols)}, created_at) "
                f"VALUES ({', '.join('%s' for _ in vals)}, %s)",
                tuple(vals + [_now()]),
            )
        return {"id": retrieval_id, "run_id": run_id, "query_index": query_index, **fields}

    @_synchronized
    def insert_tool_call(self, tool_call_id, run_id, tool_name, fields) -> dict:
        with self._connect() as conn, conn.transaction():
            cols = ["id", "run_id", "tool_name"]
            vals: list[Any] = [tool_call_id, run_id, tool_name]
            placeholders = ["%s", "%s", "%s"]
            for c in fields:
                if c == "created_at":
                    continue
                cols.append(c)
                val = fields[c]
                if c == "input_redacted" and val is not None:
                    # JSONB 列：dict -> JSON 字符串 + ::jsonb 强转
                    vals.append(_json_dumps(val))
                    placeholders.append("%s::jsonb")
                else:
                    vals.append(val)
                    placeholders.append("%s")
            conn.execute(
                f"INSERT INTO agent_run_tool_calls ({', '.join(cols)}, created_at) "
                f"VALUES ({', '.join(placeholders)}, %s)",
                tuple(vals + [_now()]),
            )
        return {"id": tool_call_id, "run_id": run_id, "tool_name": tool_name, **fields}


class FakeConversationDb(ConversationDb):
    """内存实现（单测用），接口与 PostgresConversationDb 一致。"""

    def __init__(self) -> None:
        self.write_lock = threading.RLock()
        self._conversations: dict[str, dict] = {}
        self._legacy_map: dict[str, str] = {}   # legacy_thread_id -> conversation id
        self._turns: dict[str, dict] = {}
        self._messages: dict[str, dict] = {}
        self._runs: dict[str, dict] = {}
        self._retrievals: dict[str, dict] = {}
        self._tool_calls: dict[str, dict] = {}

    # ── conversations ──

    def upsert_conversation(self, conversation_id, user_id, module, title, legacy_thread_id,
                            retrieval_scope=None) -> dict:
        existing = self._conversations.get(conversation_id)
        now = _now()
        row = {
            "id": conversation_id,
            "user_id": user_id,
            "module": module,
            "title": title if title is not None else (existing or {}).get("title"),
            "retrieval_scope": retrieval_scope if retrieval_scope is not None
            else (existing or {}).get("retrieval_scope"),
            "legacy_thread_id": legacy_thread_id if legacy_thread_id is not None
            else (existing or {}).get("legacy_thread_id"),
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
            "last_active_at": now,
            "deleted_at": (existing or {}).get("deleted_at"),
        }
        self._conversations[conversation_id] = row
        if legacy_thread_id:
            self._legacy_map[legacy_thread_id] = conversation_id
        return dict(row)

    def get_conversation(self, user_id, conversation_id) -> dict | None:
        row = self._conversations.get(conversation_id)
        if row and row["user_id"] == user_id:
            return dict(row)
        return None

    def get_conversation_by_legacy(self, user_id, legacy_thread_id) -> dict | None:
        conv_id = self._legacy_map.get(legacy_thread_id)
        if conv_id:
            return self.get_conversation(user_id, conv_id)
        return None

    def conversation_exists(self, conversation_id) -> bool:
        return conversation_id in self._conversations

    def legacy_exists(self, legacy_thread_id) -> bool:
        return legacy_thread_id in self._legacy_map

    # ── turns ──

    def insert_turn(self, turn_id, thread_id, user_id, sequence_no) -> dict:
        if any(
            t["thread_id"] == thread_id and t["sequence_no"] == sequence_no
            for t in self._turns.values()
        ):
            raise SequenceCollision(
                f"turn sequence {sequence_no} already exists for thread {thread_id}"
            )
        row = {
            "id": turn_id, "thread_id": thread_id, "user_id": user_id,
            "sequence_no": sequence_no, "created_at": _now(),
        }
        self._turns[turn_id] = row
        return dict(row)

    def max_sequence_no(self, user_id, thread_id) -> int:
        return max(
            (t["sequence_no"] for t in self._turns.values()
             if t["thread_id"] == thread_id and t["user_id"] == user_id),
            default=0,
        )

    def get_turn(self, user_id, turn_id) -> dict | None:
        row = self._turns.get(turn_id)
        if row and row["user_id"] == user_id:
            return dict(row)
        return None

    # ── messages ──

    def insert_message(self, message_id, thread_id, turn_id, user_id, role, content,
                       run_id, regenerated_from_message_id, status) -> dict:
        row = {
            "id": message_id, "thread_id": thread_id, "turn_id": turn_id,
            "user_id": user_id, "role": role, "content": content, "run_id": run_id,
            "regenerated_from_message_id": regenerated_from_message_id,
            "status": status, "created_at": _now(), "completed_at": None,
            "deleted_at": None,
        }
        self._messages[message_id] = row
        return dict(row)

    def get_message(self, user_id, message_id) -> dict | None:
        row = self._messages.get(message_id)
        if row and row["user_id"] == user_id:
            return dict(row)
        return None

    def update_message_status(self, user_id, message_id, status) -> dict:
        row = self._messages.get(message_id)
        if row and row["user_id"] == user_id:
            row["status"] = status
            row["completed_at"] = _now() if status == "completed" else None
        return dict(row) if row and row["user_id"] == user_id else {}

    def list_messages(self, user_id, thread_id) -> list[dict]:
        rows = [m for m in self._messages.values()
                if m["thread_id"] == thread_id and m["user_id"] == user_id]
        # 按 turn sequence_no、created_at 排序
        def key(m):
            turn = self._turns.get(m["turn_id"], {})
            return (turn.get("sequence_no", 0), m["created_at"], m["id"])

        rows.sort(key=key)
        return [dict(r) for r in rows]

    # ── runs ──

    def insert_run(self, run_id, user_id, thread_id, turn_id, message_id, module,
                   agent_id, model, prompt_version, agent_version, status) -> dict:
        now = _now()
        row = {
            "id": run_id, "user_id": user_id, "thread_id": thread_id, "turn_id": turn_id,
            "message_id": message_id, "module": module, "agent_id": agent_id,
            "model": model, "prompt_version": prompt_version, "agent_version": agent_version,
            "status": status, "input_tokens": None, "output_tokens": None,
            "total_tokens": None, "latency_ms": None, "langsmith_run_id": None,
            "error_type": None, "error_code": None, "error_summary": None,
            "started_at": now, "finished_at": None, "created_at": now,
        }
        self._runs[run_id] = row
        return dict(row)

    def get_run(self, user_id, run_id) -> dict | None:
        row = self._runs.get(run_id)
        if row and row["user_id"] == user_id:
            return dict(row)
        return None

    def update_run(self, user_id, run_id, fields) -> dict:
        row = self._runs.get(run_id)
        if row and row["user_id"] == user_id:
            row.update(fields)
        return self.get_run(user_id, run_id) or {}

    # ── retrievals / tool calls ──

    def insert_retrieval(self, retrieval_id, run_id, query_index, fields) -> dict:
        row = {"id": retrieval_id, "run_id": run_id, "query_index": query_index, **fields}
        self._retrievals[retrieval_id] = row
        return dict(row)

    def insert_tool_call(self, tool_call_id, run_id, tool_name, fields) -> dict:
        row = {"id": tool_call_id, "run_id": run_id, "tool_name": tool_name, **fields}
        self._tool_calls[tool_call_id] = row
        return dict(row)


def create_conversation_db(settings) -> ConversationDb:
    """按配置创建对话库：Postgres（唯一生产后端）或 Fake（仅测试 backend=fake）。"""
    backend = getattr(settings.vector_store, "backend", "")
    dsn = (settings.memory.postgres.dsn or "").strip()
    if backend == "fake":
        return FakeConversationDb()
    if not dsn:
        raise ValueError("memory.postgres.dsn 未设置（生产环境对话库必须使用 Postgres）")
    return PostgresConversationDb(dsn)
