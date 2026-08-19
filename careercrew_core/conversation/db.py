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


def _snapshot_active(snapshot: dict) -> bool:
    """Return whether a privacy snapshot is still within its retention window."""
    expires_at = snapshot.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if not isinstance(expires_at, datetime):
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)


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
        metadata: dict | None = None,
    ) -> dict: ...

    @abstractmethod
    def get_message(self, user_id: str, message_id: str) -> dict | None: ...

    @abstractmethod
    def update_message_status(self, user_id: str, message_id: str, status: str) -> dict: ...

    @abstractmethod
    def update_message_content(self, user_id: str, message_id: str, content: str,
                               status: str, metadata: dict | None = None) -> dict: ...

    @abstractmethod
    def update_message_run_id(self, user_id: str, message_id: str, run_id: str) -> dict: ...

    @abstractmethod
    def list_messages(self, user_id: str, thread_id: str) -> list[dict]: ...

    @abstractmethod
    def update_title(self, user_id: str, conversation_id: str, title: str) -> dict: ...

    @abstractmethod
    def clear_conversation(self, user_id: str, conversation_id: str) -> int: ...

    @abstractmethod
    def delete_conversation(self, user_id: str, conversation_id: str) -> bool: ...

    @abstractmethod
    def list_runs(self, user_id: str, thread_id: str) -> list[dict]: ...

    # ── runs ──

    @abstractmethod
    def insert_run(self, run_id: str, user_id: str, thread_id: str, turn_id: str,
                   message_id: str, module: str, agent_id: str, model: str,
                   prompt_version: str, agent_version: str, status: str,
                   effective_tools: list[str] | None = None) -> dict: ...

    @abstractmethod
    def get_run(self, user_id: str, run_id: str) -> dict | None: ...

    # ── regeneration idempotency ──

    @abstractmethod
    def get_regeneration(self, user_id: str, key: str) -> str | None: ...

    @abstractmethod
    def create_regeneration(self, user_id: str, key: str, message_id: str) -> str | None: ...

    @abstractmethod
    def reserve_regeneration(self, user_id: str, key: str, message_id: str | None = None) -> tuple[str, str | None]:
        """原子预留幂等键（三态契约）。

        返回三元组 (state, message_id)：
        - ``("reserved", None)``：本次成功新建预留（首个请求，应继续 dispatch）。
        - ``("exists", <message_id>)``：行已存在且 message_id 已回填（已完成，应 replay）。
        - ``("exists", None)``：行已存在且 message_id 仍为 NULL（首个请求进行中，应 409）。
        """

    @abstractmethod
    def complete_regeneration(self, user_id: str, key: str, message_id: str) -> str | None:
        """预留成功后回填最终 message_id；无对应预留返回 None。"""

    @abstractmethod
    def release_regeneration(self, user_id: str, key: str) -> bool:
        """释放未完成的预留（流中途失败不污名化该 key）；释放过返回 True。"""

    @abstractmethod
    def update_run(self, user_id: str, run_id: str, fields: dict) -> dict: ...

    # ── retrievals / tool calls ──

    @abstractmethod
    def insert_retrieval(self, retrieval_id: str, run_id: str, query_index: int,
                         fields: dict) -> dict: ...

    @abstractmethod
    def insert_tool_call(self, tool_call_id: str, run_id: str, tool_name: str,
                         fields: dict) -> dict: ...

    # ── feedback / privacy snapshots ──

    @abstractmethod
    def upsert_feedback(self, user_id: str, fields: dict) -> dict: ...

    @abstractmethod
    def list_feedback(self, user_id: str, thread_id: str) -> list[dict]: ...

    @abstractmethod
    def upsert_feedback_snapshot(self, feedback_id: str, user_id: str, fields: dict) -> dict: ...

    @abstractmethod
    def delete_feedback_snapshot(self, feedback_id: str, user_id: str) -> bool: ...

    @abstractmethod
    def delete_feedback(self, user_id: str, message_id: str) -> bool: ...

    @abstractmethod
    def insert_audit(self, actor_user_id: str, action: str, resource_type: str,
                     resource_id: str, metadata: dict) -> dict: ...

    @abstractmethod
    def replace_feedback_with_snapshot(self, user_id: str, fields: dict,
                                       snapshot_fields: dict | None) -> dict: ...

    @abstractmethod
    def delete_feedback_with_audit(self, user_id: str, message_id: str,
                                   metadata: dict) -> bool: ...

    # ── quality reviewer read models ──

    @abstractmethod
    def list_quality_feedback(self) -> list[dict]: ...

    @abstractmethod
    def get_quality_feedback(self, feedback_id: str) -> dict | None: ...

    @abstractmethod
    def get_quality_snapshot(self, feedback_id: str) -> dict | None: ...

    @abstractmethod
    def get_quality_diagnostics(self, feedback_id: str) -> dict | None: ...

    # ── feedback reviews（人工归因）──

    @abstractmethod
    def get_feedback_review(self, feedback_id: str) -> dict | None: ...

    @abstractmethod
    def upsert_feedback_review(self, fields: dict, events: list[dict],
                               audits: list[dict]) -> dict: ...

    # ── quality metrics（T5.2 Dashboard）──

    @abstractmethod
    def compute_quality_metrics(self, filters: dict) -> dict: ...

    # ── eval cases（Phase 6：Bad Case → Eval Dataset，§29）──

    @abstractmethod
    def list_eval_cases(self, status: str | None = None) -> list[dict]: ...

    @abstractmethod
    def get_eval_case(self, case_id: str) -> dict | None: ...

    @abstractmethod
    def insert_eval_case(self, fields: dict, audits: list[dict]) -> dict: ...

    @abstractmethod
    def update_eval_case(self, case_id: str, fields: dict, audits: list[dict]) -> dict: ...


class PostgresConversationDb(ConversationDb):
    """Postgres 实现（psycopg 3）。连接惰性建立：首次操作才 connect + 建表。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connected = False
        self.write_lock = threading.RLock()
        self._connect_timeout = 5

    def _connect(self):
        if not self._connected:
            self._ensure()
        import psycopg

        return psycopg.connect(
            self._dsn, row_factory=psycopg.rows.dict_row, connect_timeout=self._connect_timeout
        )

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
        with psycopg.connect(
            self._dsn, row_factory=psycopg.rows.dict_row, connect_timeout=self._connect_timeout
        ) as conn, conn.transaction():
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
            # metadata JSONB：assistant 富结构（knowledge sources / consult opinions+calls），
            # 幂等迁移追加；历史行回退 NULL（见 T1.3 brief）。
            conn.execute("SET lock_timeout = '5s'")
            try:
                conn.execute(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'messages' AND column_name = 'metadata') THEN "
                    "ALTER TABLE messages ADD COLUMN metadata JSONB; "
                    "END IF; END $$"
                )
            finally:
                conn.execute("SET lock_timeout = '0'")
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
            # T3.5：effective_tools JSONB（本轮最终允许的工具 id 列表，可诊断）。
            # 幂等迁移；历史行回退 NULL（见 t35 brief §16.3）。
            conn.execute("SET lock_timeout = '5s'")
            try:
                conn.execute(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'agent_runs' AND column_name = 'effective_tools') THEN "
                    "ALTER TABLE agent_runs ADD COLUMN effective_tools JSONB; "
                    "END IF; END $$"
                )
            finally:
                conn.execute("SET lock_timeout = '0'")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agent_run_retrievals ("
                "id UUID PRIMARY KEY, run_id UUID NOT NULL, query_index INTEGER NOT NULL, "
                "query_text_redacted TEXT, scope VARCHAR(50), document_id VARCHAR(255), "
                "chunk_id VARCHAR(255), recall_score DOUBLE PRECISION, "
                "rerank_score DOUBLE PRECISION, rank_before INTEGER, rank_after INTEGER, "
                "used_in_final_context BOOLEAN NOT NULL DEFAULT FALSE, "
                "created_at TIMESTAMPTZ NOT NULL)"
            )
            # T3.4：retrieval_source 区分 mention（强制上下文）与 auto（Agent 自动检索）。
            # 幂等迁移：存量行被回填为 'auto'（ADD COLUMN ... DEFAULT 'auto'）；读侧对缺失/None 仍按 'auto' 兜底（见 store.add_retrieval 默认）。
            conn.execute("SET lock_timeout = '5s'")
            try:
                conn.execute(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'agent_run_retrievals' AND column_name = 'retrieval_source') THEN "
                    "ALTER TABLE agent_run_retrievals ADD COLUMN retrieval_source VARCHAR(30) NOT NULL DEFAULT 'auto'; "
                    "END IF; END $$"
                )
            finally:
                conn.execute("SET lock_timeout = '0'")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agent_run_tool_calls ("
                "id UUID PRIMARY KEY, run_id UUID NOT NULL, tool_name VARCHAR(150) NOT NULL, "
                "input_redacted JSONB, output_summary TEXT, status VARCHAR(30) NOT NULL, "
                "duration_ms INTEGER, requires_hitl BOOLEAN NOT NULL DEFAULT FALSE, "
                "hitl_status VARCHAR(30), error_type VARCHAR(100), error_summary TEXT, "
                "started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, "
                "created_at TIMESTAMPTZ NOT NULL)"
            )
            # regenerate 幂等表（§38）：同 (user_id, key) 唯一，二次请求复用首次结果。
            conn.execute(
                "CREATE TABLE IF NOT EXISTS regeneration_keys ("
                "user_id VARCHAR(64) NOT NULL, key VARCHAR(200) NOT NULL, "
                "message_id UUID, created_at TIMESTAMPTZ NOT NULL, "
                "UNIQUE(user_id, key))"
            )
            # Feedback domain: kept separate from conversation data so Phase 5 can
            # grant narrowly-scoped reviewer access without exposing messages.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS message_feedback ("
                "id UUID PRIMARY KEY, user_id VARCHAR(64) NOT NULL, thread_id UUID NOT NULL, "
                "turn_id UUID NOT NULL, message_id UUID NOT NULL, run_id UUID NOT NULL, "
                "rating VARCHAR(16) NOT NULL, reason VARCHAR(50), comment TEXT, "
                "share_context BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL, "
                "updated_at TIMESTAMPTZ NOT NULL, UNIQUE(user_id, message_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS feedback_snapshots ("
                "id UUID PRIMARY KEY, feedback_id UUID NOT NULL UNIQUE REFERENCES message_feedback(id) ON DELETE CASCADE, "
                "user_id VARCHAR(64) NOT NULL, snapshot_json JSONB NOT NULL, "
                "redaction_version VARCHAR(80) NOT NULL, redaction_count INTEGER NOT NULL, "
                "expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS feedback_audit_log ("
                "id UUID PRIMARY KEY, actor_user_id VARCHAR(64) NOT NULL, action VARCHAR(80) NOT NULL, "
                "resource_type VARCHAR(80) NOT NULL, resource_id VARCHAR(128) NOT NULL, "
                "metadata JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL)"
            )
            # T5.4 人工归因：review 当前状态 + 全量变更事件（§27）。与 message_feedback
            # 同域隔离：reviewer 只写自己的归因元数据，永远不接触用户正文。
            conn.execute(
                "CREATE TABLE IF NOT EXISTS feedback_reviews ("
                "id UUID PRIMARY KEY, feedback_id UUID NOT NULL UNIQUE REFERENCES message_feedback(id) ON DELETE CASCADE, "
                "reviewer_user_id VARCHAR(64) NOT NULL, "
                "root_cause VARCHAR(50), status VARCHAR(50) NOT NULL, "
                "reviewer_note TEXT, "
                "created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS feedback_review_events ("
                "id UUID PRIMARY KEY, feedback_id UUID NOT NULL, reviewer_user_id VARCHAR(64) NOT NULL, "
                "event_type VARCHAR(50) NOT NULL, old_value JSONB, new_value JSONB, "
                "created_at TIMESTAMPTZ NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_review_events_feedback "
                "ON feedback_review_events(feedback_id, created_at)"
            )
            # Phase 6（§29.3）：Bad Case → Eval 数据集。只存脱敏后输入/必要上下文与
            # 评审填写的期望行为/评分细则，绝不引用完整正文。
            conn.execute(
                "CREATE TABLE IF NOT EXISTS eval_cases ("
                "id UUID PRIMARY KEY, "
                "source_feedback_id UUID NOT NULL REFERENCES message_feedback(id) ON DELETE CASCADE, "
                "status VARCHAR(30) NOT NULL, "
                "target_agent VARCHAR(100) NOT NULL, "
                "input_text TEXT NOT NULL, "
                "context_json JSONB, "
                "expected_behavior TEXT, "
                "rubric JSONB NOT NULL, "
                "failure_reason VARCHAR(100), "
                "source_model VARCHAR(150), "
                "source_prompt_version VARCHAR(80), "
                "source_agent_version VARCHAR(80), "
                "created_by VARCHAR(64) NOT NULL, "
                "approved_by VARCHAR(64), "
                "created_at TIMESTAMPTZ NOT NULL, "
                "approved_at TIMESTAMPTZ)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_eval_cases_status "
                "ON eval_cases(status, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_feedback_user_thread "
                "ON message_feedback(user_id, thread_id, updated_at DESC)"
            )
            # T1.6 上游预留：message_id 允许 NULL（预留时尚未生成最终 message），
            # 完成后回填。存量表迁移 DROP NOT NULL。
            conn.execute("SET lock_timeout = '5s'")
            try:
                conn.execute(
                    "DO $$ BEGIN "
                    "IF EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'regeneration_keys' AND column_name = 'message_id' "
                    "AND is_nullable = 'NO') THEN "
                    "ALTER TABLE regeneration_keys ALTER COLUMN message_id DROP NOT NULL; "
                    "END IF; END $$"
                )
            finally:
                conn.execute("SET lock_timeout = '0'")
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
                       run_id, regenerated_from_message_id, status, metadata=None) -> dict:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO messages (id, thread_id, turn_id, user_id, role, content, "
                "run_id, regenerated_from_message_id, status, metadata, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                (message_id, thread_id, turn_id, user_id, role, content, run_id,
                 regenerated_from_message_id, status,
                 _json_dumps(metadata) if metadata is not None else None, _now()),
            )
        return self.get_message(user_id, message_id) or {}

    @_synchronized
    def get_message(self, user_id, message_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, thread_id, turn_id, user_id, role, content, run_id, "
                "regenerated_from_message_id, status, created_at, completed_at, deleted_at, metadata "
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
    def update_message_content(self, user_id, message_id, content, status, metadata=None) -> dict:
        with self._connect() as conn, conn.transaction():
            completed_at = _now() if status == "completed" else None
            conn.execute(
                "UPDATE messages SET content=%s, status=%s, completed_at=%s, "
                "metadata=COALESCE(%s::jsonb, metadata) "
                "WHERE id=%s AND user_id=%s",
                (content, status, completed_at,
                 _json_dumps(metadata) if metadata is not None else None,
                 message_id, user_id),
            )
        return self._read_message(user_id, message_id)

    @_synchronized
    def update_message_run_id(self, user_id, message_id, run_id) -> dict:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "UPDATE messages SET run_id=%s WHERE id=%s AND user_id=%s",
                (run_id, message_id, user_id),
            )
        return self._read_message(user_id, message_id)

    @_synchronized
    def _read_message(self, user_id, message_id) -> dict:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, thread_id, turn_id, user_id, role, content, run_id, "
                "regenerated_from_message_id, status, created_at, completed_at, deleted_at, metadata "
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
                "m.completed_at, m.deleted_at, m.metadata "
                "FROM messages m "
                "JOIN conversation_turns t ON t.id = m.turn_id "
                "WHERE m.thread_id=%s AND m.user_id=%s "
                "ORDER BY t.sequence_no, m.created_at, m.id",
                (thread_id, user_id),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    @_synchronized
    def update_title(self, user_id, conversation_id, title) -> dict:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "UPDATE conversations SET title=%s, updated_at=%s "
                "WHERE id=%s AND user_id=%s",
                (title, _now(), conversation_id, user_id),
            )
        return self.get_conversation(user_id, conversation_id) or {}

    @_synchronized
    def clear_conversation(self, user_id, conversation_id) -> int:
        """删除该会话所有 turns（级联 messages），保留 conversation 行。

        返回删除的 turn 数。message 行先按 thread_id 硬删（messages.thread_id 无 FK），
        turns 再删。runs/retrievals/tool_calls 一并清理，避免悬挂 run 引用。
        """
        with self._connect() as conn, conn.transaction():
            # regeneration_keys 孤儿清理：先删（其 message_id 指向将被删除的 messages），
            # 作用域限定为受影响 thread 的消息，避免误删他人幂等键。
            conn.execute(
                "DELETE FROM regeneration_keys WHERE message_id IN "
                "(SELECT id FROM messages WHERE thread_id=%s AND user_id=%s)",
                (conversation_id, user_id),
            )
            # Conversation deletion is an immediate privacy revocation for its
            # feedback snapshots as well. Delete child rows explicitly so the
            # operation remains correct if the FK is added to legacy databases later.
            conn.execute(
                "DELETE FROM feedback_snapshots WHERE feedback_id IN "
                "(SELECT id FROM message_feedback WHERE thread_id=%s AND user_id=%s)",
                (conversation_id, user_id),
            )
            conn.execute(
                "DELETE FROM message_feedback WHERE thread_id=%s AND user_id=%s",
                (conversation_id, user_id),
            )
            # runs 关联的 retrievals / tool_calls 先删（按 run_id 子查询归属该 thread）
            conn.execute(
                "DELETE FROM agent_run_tool_calls WHERE run_id IN "
                "(SELECT id FROM agent_runs WHERE thread_id=%s AND user_id=%s)",
                (conversation_id, user_id),
            )
            conn.execute(
                "DELETE FROM agent_run_retrievals WHERE run_id IN "
                "(SELECT id FROM agent_runs WHERE thread_id=%s AND user_id=%s)",
                (conversation_id, user_id),
            )
            conn.execute(
                "DELETE FROM agent_runs WHERE thread_id=%s AND user_id=%s",
                (conversation_id, user_id),
            )
            conn.execute(
                "DELETE FROM messages WHERE thread_id=%s AND user_id=%s",
                (conversation_id, user_id),
            )
            cur = conn.execute(
                "DELETE FROM conversation_turns WHERE thread_id=%s AND user_id=%s",
                (conversation_id, user_id),
            )
            n = cur.rowcount
        return n

    @_synchronized
    def delete_conversation(self, user_id, conversation_id) -> bool:
        """硬删 conversation 及其全部子表行（turns/messages/runs/retrievals/tool_calls）。"""
        with self._connect() as conn, conn.transaction():
            self.clear_conversation(user_id, conversation_id)
            cur = conn.execute(
                "DELETE FROM conversations WHERE id=%s AND user_id=%s",
                (conversation_id, user_id),
            )
        return bool(cur.rowcount)

    @_synchronized
    def list_runs(self, user_id, thread_id) -> list[dict]:
        with self._connect() as conn, conn.transaction():
            rows = conn.execute(
                "SELECT id, user_id, thread_id, turn_id, message_id, module, agent_id, "
                "model, prompt_version, agent_version, status, input_tokens, "
                "output_tokens, total_tokens, latency_ms, langsmith_run_id, error_type, "
                "error_code, error_summary, effective_tools, started_at, finished_at, created_at "
                "FROM agent_runs WHERE thread_id=%s AND user_id=%s "
                "ORDER BY created_at, id",
                (thread_id, user_id),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # ── runs ──

    @_synchronized
    def insert_run(self, run_id, user_id, thread_id, turn_id, message_id, module,
                   agent_id, model, prompt_version, agent_version, status,
                   effective_tools=None) -> dict:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO agent_runs (id, user_id, thread_id, turn_id, message_id, "
                "module, agent_id, model, prompt_version, agent_version, status, "
                "effective_tools, started_at, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                (run_id, user_id, thread_id, turn_id, message_id, module, agent_id,
                 model, prompt_version, agent_version, status,
                 _json_dumps(effective_tools) if effective_tools is not None else None,
                 _now(), _now()),
            )
        return self.get_run(user_id, run_id) or {}

    @_synchronized
    def get_run(self, user_id, run_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, user_id, thread_id, turn_id, message_id, module, agent_id, "
                "model, prompt_version, agent_version, status, input_tokens, "
                "output_tokens, total_tokens, latency_ms, langsmith_run_id, error_type, "
                "error_code, error_summary, effective_tools, started_at, finished_at, created_at "
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

    # ── regeneration idempotency ──

    @_synchronized
    def get_regeneration(self, user_id, key) -> str | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT message_id FROM regeneration_keys WHERE user_id=%s AND key=%s",
                (user_id, key),
            ).fetchone()
        return str(row["message_id"]) if row else None

    @_synchronized
    def create_regeneration(self, user_id, key, message_id) -> str | None:
        with self._connect() as conn, conn.transaction():
            try:
                conn.execute(
                    "INSERT INTO regeneration_keys (user_id, key, message_id, created_at) "
                    "VALUES (%s, %s, %s, %s)",
                    (user_id, key, message_id, _now()),
                )
            except Exception as err:
                if _is_unique_violation(err):
                    # 幂等命中：已存在同 (user_id, key)，返回 None（调用方用
                    # get_regeneration 复用首次结果；与 Fake 实现/契约一致）。
                    return None
                raise
        return message_id

    @_synchronized
    def reserve_regeneration(self, user_id, key, message_id=None) -> tuple[str, str | None]:
        """原子预留：INSERT ... ON CONFLICT DO NOTHING + 读回（三态）。

        - 本次插入成功 → ``("reserved", None)``（成功预留，应 dispatch）。
        - 已存在 → ``("exists", <message_id>)``，message_id 为 None 表示首个请求仍进行中。
        """
        with self._connect() as conn, conn.transaction():
            cur = conn.execute(
                "INSERT INTO regeneration_keys (user_id, key, message_id, created_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (user_id, key) DO NOTHING",
                (user_id, key, message_id, _now()),
            )
            if cur.rowcount:
                return ("reserved", None)  # 本次插入成功，成功预留
            row = conn.execute(
                "SELECT message_id FROM regeneration_keys WHERE user_id=%s AND key=%s",
                (user_id, key),
            ).fetchone()
            if row is None:
                # 理论不可达：无冲突却无行。按预留成功处理，避免误报冲突。
                return ("reserved", None)
            mid = row["message_id"]
        return ("exists", str(mid) if mid is not None else None)

    @_synchronized
    def complete_regeneration(self, user_id, key, message_id) -> str | None:
        with self._connect() as conn, conn.transaction():
            cur = conn.execute(
                "UPDATE regeneration_keys SET message_id=%s WHERE user_id=%s AND key=%s "
                "RETURNING message_id",
                (message_id, user_id, key),
            )
            row = cur.fetchone()
        return str(row["message_id"]) if row else None

    @_synchronized
    def release_regeneration(self, user_id, key) -> bool:
        with self._connect() as conn, conn.transaction():
            cur = conn.execute(
                "DELETE FROM regeneration_keys WHERE user_id=%s AND key=%s",
                (user_id, key),
            )
        return bool(cur.rowcount)

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

    # ── feedback / privacy snapshots ──

    @_synchronized
    def upsert_feedback(self, user_id, fields) -> dict:
        with self._connect() as conn, conn.transaction():
            now = _now()
            conn.execute(
                "INSERT INTO message_feedback (id, user_id, thread_id, turn_id, message_id, run_id, "
                "rating, reason, comment, share_context, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (user_id, message_id) DO UPDATE SET rating=EXCLUDED.rating, "
                "reason=EXCLUDED.reason, comment=EXCLUDED.comment, share_context=EXCLUDED.share_context, "
                "thread_id=EXCLUDED.thread_id, turn_id=EXCLUDED.turn_id, run_id=EXCLUDED.run_id, "
                "updated_at=EXCLUDED.updated_at",
                (fields["id"], user_id, fields["thread_id"], fields["turn_id"], fields["message_id"],
                 fields["run_id"], fields["rating"], fields.get("reason"), fields.get("comment"),
                 fields["share_context"], now, now),
            )
            row = conn.execute(
                "SELECT id, user_id, thread_id, turn_id, message_id, run_id, rating, reason, comment, "
                "share_context, created_at, updated_at FROM message_feedback WHERE user_id=%s AND message_id=%s",
                (user_id, fields["message_id"]),
            ).fetchone()
        return _row_to_dict(row) if row else {}

    @_synchronized
    def list_feedback(self, user_id, thread_id) -> list[dict]:
        with self._connect() as conn, conn.transaction():
            rows = conn.execute(
                "SELECT id, message_id, rating, reason, comment, share_context, created_at, updated_at "
                "FROM message_feedback WHERE user_id=%s AND thread_id=%s ORDER BY updated_at, id",
                (user_id, thread_id),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    @_synchronized
    def upsert_feedback_snapshot(self, feedback_id, user_id, fields) -> dict:
        with self._connect() as conn, conn.transaction():
            now = _now()
            snapshot_id = fields["id"]
            conn.execute(
                "INSERT INTO feedback_snapshots (id, feedback_id, user_id, snapshot_json, redaction_version, "
                "redaction_count, expires_at, created_at) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s) "
                "ON CONFLICT (feedback_id) DO UPDATE SET snapshot_json=EXCLUDED.snapshot_json, "
                "redaction_version=EXCLUDED.redaction_version, redaction_count=EXCLUDED.redaction_count, "
                "expires_at=EXCLUDED.expires_at, created_at=EXCLUDED.created_at",
                (snapshot_id, feedback_id, user_id, _json_dumps(fields["snapshot_json"]),
                 fields["redaction_version"], fields["redaction_count"], fields["expires_at"], now),
            )
            row = conn.execute(
                "SELECT id, feedback_id, user_id, snapshot_json, redaction_version, redaction_count, expires_at, created_at "
                "FROM feedback_snapshots WHERE feedback_id=%s AND user_id=%s", (feedback_id, user_id),
            ).fetchone()
        return _row_to_dict(row) if row else {}

    @_synchronized
    def delete_feedback_snapshot(self, feedback_id, user_id) -> bool:
        with self._connect() as conn, conn.transaction():
            cur = conn.execute(
                "DELETE FROM feedback_snapshots WHERE feedback_id=%s AND user_id=%s", (feedback_id, user_id)
            )
        return bool(cur.rowcount)

    @_synchronized
    def delete_feedback(self, user_id, message_id) -> bool:
        with self._connect() as conn, conn.transaction():
            cur = conn.execute(
                "DELETE FROM message_feedback WHERE user_id=%s AND message_id=%s", (user_id, message_id)
            )
        return bool(cur.rowcount)

    @_synchronized
    def insert_audit(self, actor_user_id, action, resource_type, resource_id, metadata) -> dict:
        row = {"id": str(uuid7()), "actor_user_id": actor_user_id, "action": action,
               "resource_type": resource_type, "resource_id": resource_id,
               "metadata": metadata, "created_at": _now()}
        with self._connect() as conn, conn.transaction():
            conn.execute(
                "INSERT INTO feedback_audit_log (id, actor_user_id, action, resource_type, resource_id, metadata, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)",
                (row["id"], row["actor_user_id"], row["action"], row["resource_type"], row["resource_id"],
                 _json_dumps(row["metadata"]), row["created_at"]),
            )
        return row

    @_synchronized
    def replace_feedback_with_snapshot(self, user_id, fields, snapshot_fields) -> dict:
        """Persist the current consent state and its snapshot in one transaction."""
        if fields["rating"] != "negative" or not fields["share_context"]:
            snapshot_fields = None
        with self._connect() as conn, conn.transaction():
            now = _now()
            conn.execute(
                "INSERT INTO message_feedback (id, user_id, thread_id, turn_id, message_id, run_id, "
                "rating, reason, comment, share_context, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (user_id, message_id) DO UPDATE SET rating=EXCLUDED.rating, "
                "reason=EXCLUDED.reason, comment=EXCLUDED.comment, share_context=EXCLUDED.share_context, "
                "thread_id=EXCLUDED.thread_id, turn_id=EXCLUDED.turn_id, run_id=EXCLUDED.run_id, "
                "updated_at=EXCLUDED.updated_at",
                (fields["id"], user_id, fields["thread_id"], fields["turn_id"], fields["message_id"],
                 fields["run_id"], fields["rating"], fields.get("reason"), fields.get("comment"),
                 fields["share_context"], now, now),
            )
            row = conn.execute(
                "SELECT id, user_id, thread_id, turn_id, message_id, run_id, rating, reason, comment, "
                "share_context, created_at, updated_at FROM message_feedback WHERE user_id=%s AND message_id=%s",
                (user_id, fields["message_id"]),
            ).fetchone()
            feedback = _row_to_dict(row) if row else {}
            if snapshot_fields is None:
                conn.execute("DELETE FROM feedback_snapshots WHERE feedback_id=%s AND user_id=%s", (feedback["id"], user_id))
            else:
                conn.execute(
                    "INSERT INTO feedback_snapshots (id, feedback_id, user_id, snapshot_json, redaction_version, "
                    "redaction_count, expires_at, created_at) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s) "
                    "ON CONFLICT (feedback_id) DO UPDATE SET snapshot_json=EXCLUDED.snapshot_json, "
                    "redaction_version=EXCLUDED.redaction_version, redaction_count=EXCLUDED.redaction_count, "
                    "expires_at=EXCLUDED.expires_at, created_at=EXCLUDED.created_at",
                    (snapshot_fields["id"], feedback["id"], user_id, _json_dumps(snapshot_fields["snapshot_json"]),
                     snapshot_fields["redaction_version"], snapshot_fields["redaction_count"],
                     snapshot_fields["expires_at"], now),
                )
        return feedback

    @_synchronized
    def delete_feedback_with_audit(self, user_id, message_id, metadata) -> bool:
        """Delete feedback/snapshot and add its audit row as one transaction."""
        audit = {"id": str(uuid7()), "actor_user_id": user_id, "action": "feedback.deleted",
                 "resource_type": "message_feedback", "resource_id": message_id,
                 "metadata": dict(metadata), "created_at": _now()}
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id FROM message_feedback WHERE user_id=%s AND message_id=%s FOR UPDATE",
                (user_id, message_id),
            ).fetchone()
            deleted = row is not None
            if audit["metadata"].get("deleted") is None:
                audit["metadata"]["deleted"] = deleted
            if row:
                conn.execute("DELETE FROM feedback_snapshots WHERE feedback_id=%s AND user_id=%s", (row["id"], user_id))
                conn.execute("DELETE FROM message_feedback WHERE id=%s AND user_id=%s", (row["id"], user_id))
            conn.execute(
                "INSERT INTO feedback_audit_log (id, actor_user_id, action, resource_type, resource_id, metadata, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)",
                (audit["id"], audit["actor_user_id"], audit["action"], audit["resource_type"], audit["resource_id"],
                 _json_dumps(audit["metadata"]), audit["created_at"]),
            )
        return deleted

    # ── quality reviewer read models ──

    @staticmethod
    def _quality_feedback_sql(where: str = "") -> str:
        return (
            "SELECT f.id AS feedback_id, f.run_id, f.reason, f.share_context, f.created_at, f.updated_at, "
            "r.module, r.agent_id, r.model, r.prompt_version, r.agent_version, r.status, "
            "r.input_tokens, r.output_tokens, r.total_tokens, r.latency_ms, r.error_type, r.error_code, "
            "rv.status AS review_status, rv.root_cause, "
            "(s.id IS NOT NULL AND s.expires_at > now()) AS snapshot_available "
            "FROM message_feedback f JOIN agent_runs r ON r.id=f.run_id AND r.user_id=f.user_id "
            "LEFT JOIN feedback_snapshots s ON s.feedback_id=f.id AND s.user_id=f.user_id "
            "LEFT JOIN feedback_reviews rv ON rv.feedback_id=f.id "
            "WHERE f.rating='negative' " + where
        )

    @_synchronized
    def list_quality_feedback(self) -> list[dict]:
        with self._connect() as conn, conn.transaction():
            rows = conn.execute(
                self._quality_feedback_sql() + "ORDER BY f.updated_at DESC, f.id"
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    @_synchronized
    def get_quality_feedback(self, feedback_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                self._quality_feedback_sql("AND f.id=%s "), (feedback_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def get_quality_snapshot(self, feedback_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT s.id AS snapshot_id, s.snapshot_json, s.redaction_version, s.redaction_count, "
                "s.expires_at, s.created_at FROM message_feedback f "
                "JOIN feedback_snapshots s ON s.feedback_id=f.id AND s.user_id=f.user_id "
                "WHERE f.id=%s AND f.rating='negative' AND s.expires_at > now()",
                (feedback_id,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def get_quality_diagnostics(self, feedback_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            run = conn.execute(
                "SELECT r.id AS run_id, r.module, r.agent_id, r.model, r.prompt_version, r.agent_version, "
                "r.status, r.input_tokens, r.output_tokens, r.total_tokens, r.latency_ms, r.error_type, "
                "r.error_code, r.effective_tools, r.started_at, r.finished_at, r.created_at "
                "FROM message_feedback f JOIN agent_runs r ON r.id=f.run_id AND r.user_id=f.user_id "
                "WHERE f.id=%s AND f.rating='negative'",
                (feedback_id,),
            ).fetchone()
            if run is None:
                return None
            run_row = _row_to_dict(run)
            retrievals = conn.execute(
                "SELECT document_id, chunk_id, recall_score, rerank_score, rank_before, rank_after, "
                "used_in_final_context, retrieval_source FROM agent_run_retrievals WHERE run_id=%s "
                "ORDER BY query_index, id",
                (run_row["run_id"],),
            ).fetchall()
            tool_calls = conn.execute(
                "SELECT tool_name, status, duration_ms, requires_hitl, hitl_status, error_type "
                "FROM agent_run_tool_calls WHERE run_id=%s ORDER BY created_at, id",
                (run_row["run_id"],),
            ).fetchall()
        return {
            "run": run_row,
            "retrievals": [_row_to_dict(row) for row in retrievals],
            "tool_calls": [_row_to_dict(row) for row in tool_calls],
        }

    # ── feedback reviews（人工归因）──

    @_synchronized
    def get_feedback_review(self, feedback_id) -> dict | None:
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "SELECT id, feedback_id, reviewer_user_id, root_cause, "
                "status AS review_status, reviewer_note, created_at, updated_at "
                "FROM feedback_reviews WHERE feedback_id=%s",
                (feedback_id,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    @_synchronized
    def upsert_feedback_review(self, fields, events, audits) -> dict:
        """Atomically upsert a review row and append its change events + audit rows."""
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "INSERT INTO feedback_reviews (id, feedback_id, reviewer_user_id, root_cause, status, "
                "reviewer_note, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (feedback_id) DO UPDATE SET "
                "reviewer_user_id=EXCLUDED.reviewer_user_id, root_cause=EXCLUDED.root_cause, "
                "status=EXCLUDED.status, reviewer_note=EXCLUDED.reviewer_note, "
                "updated_at=EXCLUDED.updated_at RETURNING id, feedback_id, reviewer_user_id, "
                "root_cause, status AS review_status, reviewer_note, created_at, updated_at",
                (fields["id"], fields["feedback_id"], fields["reviewer_user_id"],
                 fields.get("root_cause"), fields["status"], fields.get("reviewer_note"),
                 fields["created_at"], fields["updated_at"]),
            ).fetchone()
            for event in events:
                conn.execute(
                    "INSERT INTO feedback_review_events (id, feedback_id, reviewer_user_id, "
                    "event_type, old_value, new_value, created_at) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)",
                    (event["id"], fields["feedback_id"], event["reviewer_user_id"],
                     event["event_type"], _json_dumps(event.get("old_value")),
                     _json_dumps(event.get("new_value")), event["created_at"]),
                )
            for audit in audits:
                conn.execute(
                    "INSERT INTO feedback_audit_log (id, actor_user_id, action, resource_type, resource_id, "
                    "metadata, created_at) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)",
                    (audit["id"], audit["actor_user_id"], audit["action"], audit["resource_type"],
                     audit["resource_id"], _json_dumps(audit["metadata"]), audit["created_at"]),
                )
        return _row_to_dict(row)

    @staticmethod
    def _eval_case_row(row: dict | None) -> dict | None:
        if row is None:
            return None
        out = dict(row)
        out["context"] = out.pop("context_json")
        return out

    def list_eval_cases(self, status=None) -> list[dict]:
        sql = "SELECT * FROM eval_cases"
        params: tuple = ()
        if status:
            sql += " WHERE status=%s"
            params = (status,)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._eval_case_row(r) for r in rows]

    def get_eval_case(self, case_id) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM eval_cases WHERE id=%s", (case_id,)).fetchone()
        return self._eval_case_row(row)

    @_synchronized
    def insert_eval_case(self, fields, audits) -> dict:
        """Atomically insert an eval case and its audit rows (draft created)."""
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "INSERT INTO eval_cases (id, source_feedback_id, status, target_agent, input_text, "
                "context_json, expected_behavior, rubric, failure_reason, source_model, "
                "source_prompt_version, source_agent_version, created_by, approved_by, "
                "created_at, approved_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING *",
                (fields["id"], fields["source_feedback_id"], fields["status"],
                 fields["target_agent"], fields["input_text"],
                 _json_dumps(fields.get("context")), fields.get("expected_behavior"),
                 _json_dumps(fields["rubric"]), fields.get("failure_reason"),
                 fields.get("source_model"), fields.get("source_prompt_version"),
                 fields.get("source_agent_version"), fields["created_by"],
                 fields.get("approved_by"), fields["created_at"], fields.get("approved_at")),
            ).fetchone()
            for audit in audits:
                conn.execute(
                    "INSERT INTO feedback_audit_log (id, actor_user_id, action, resource_type, "
                    "resource_id, metadata, created_at) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)",
                    (audit["id"], audit["actor_user_id"], audit["action"], audit["resource_type"],
                     audit["resource_id"], _json_dumps(audit["metadata"]), audit["created_at"]),
                )
        return self._eval_case_row(row)

    @_synchronized
    def update_eval_case(self, case_id, fields, audits) -> dict:
        """Atomically update an eval case and append its audit rows."""
        sets: list[str] = []
        params: list = []
        for column in ("status", "target_agent", "expected_behavior", "failure_reason",
                       "source_model", "source_prompt_version", "source_agent_version"):
            if column in fields:
                sets.append(f"{column}=%s")
                params.append(fields[column])
        if "input_text" in fields:
            sets.append("input_text=%s")
            params.append(fields["input_text"])
        if "context" in fields:
            sets.append("context_json=%s")
            params.append(_json_dumps(fields["context"]))
        if "rubric" in fields:
            sets.append("rubric=%s")
            params.append(_json_dumps(fields["rubric"]))
        if "approved_by" in fields:
            sets.append("approved_by=%s")
            params.append(fields["approved_by"])
        if "approved_at" in fields:
            sets.append("approved_at=%s")
            params.append(fields["approved_at"])
        if "updated_at" in fields:
            sets.append("updated_at=%s")
            params.append(fields["updated_at"])
        if not sets:
            raise ValueError("eval case 无更新字段")
        params.append(case_id)
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                f"UPDATE eval_cases SET {', '.join(sets)} WHERE id=%s RETURNING *",
                params,
            ).fetchone()
            for audit in audits:
                conn.execute(
                    "INSERT INTO feedback_audit_log (id, actor_user_id, action, resource_type, "
                    "resource_id, metadata, created_at) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)",
                    (audit["id"], audit["actor_user_id"], audit["action"], audit["resource_type"],
                     audit["resource_id"], _json_dumps(audit["metadata"]), audit["created_at"]),
                )
        return self._eval_case_row(row)

    @staticmethod
    def _metrics_clauses(filters: dict) -> tuple[str, list]:
        """Build a run-scoped WHERE fragment from dashboard filters (T5.2)."""
        clauses: list[str] = []
        params: list = []
        if filters.get("from_dt") is not None:
            clauses.append("r.started_at >= %s")
            params.append(filters["from_dt"])
        if filters.get("to_dt") is not None:
            clauses.append("r.started_at < %s")
            params.append(filters["to_dt"])
        for column, key in (("module", "module"), ("agent_id", "agent"),
                            ("model", "model"), ("prompt_version", "prompt_version"),
                            ("agent_version", "agent_version")):
            value = filters.get(key)
            if value:
                clauses.append(f"r.{column}=%s")
                params.append(value)
        return (" AND " + " AND ".join(clauses)) if clauses else "", params

    @_synchronized
    def compute_quality_metrics(self, filters: dict) -> dict:
        """Aggregate feedback/run metrics within a single run scope (§25.2 + T5.5)."""
        where, params = self._metrics_clauses(filters)
        with self._connect() as conn, conn.transaction():
            run_row = conn.execute(
                "SELECT COUNT(*) AS runs, COUNT(latency_ms) AS latency_n, "
                "percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS median_latency_ms, "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms, "
                "AVG(input_tokens) AS avg_input_tokens, AVG(output_tokens) AS avg_output_tokens, "
                "COUNT(*) FILTER (WHERE prompt_version IS NULL OR prompt_version='' "
                "OR prompt_version='unversioned' OR agent_version IS NULL OR agent_version='' "
                "OR agent_version='unversioned') AS unversioned_runs "
                "FROM agent_runs r WHERE 1=1" + where,
                params,
            ).fetchone()
            ratings = conn.execute(
                "SELECT f.rating, COUNT(*) AS n FROM message_feedback f "
                "JOIN agent_runs r ON r.id=f.run_id AND r.user_id=f.user_id "
                "WHERE 1=1" + where + " GROUP BY f.rating",
                params,
            ).fetchall()
            reasons = conn.execute(
                "SELECT f.reason, COUNT(*) AS n FROM message_feedback f "
                "JOIN agent_runs r ON r.id=f.run_id AND r.user_id=f.user_id "
                "WHERE f.rating='negative' AND 1=1" + where + " GROUP BY f.reason",
                params,
            ).fetchall()
            trend = conn.execute(
                "SELECT r.prompt_version, "
                "COUNT(f.id) FILTER (WHERE f.rating='positive') AS positive_count, "
                "COUNT(f.id) AS feedback_count "
                "FROM agent_runs r LEFT JOIN message_feedback f "
                "ON f.run_id=r.id AND f.user_id=r.user_id "
                "WHERE 1=1" + where + " GROUP BY r.prompt_version ORDER BY r.prompt_version",
                params,
            ).fetchall()
        run = _row_to_dict(run_row)
        total = int(run["runs"] or 0)
        rating_map = {row["rating"]: int(row["n"]) for row in ratings}
        positive = rating_map.get("positive", 0)
        negative = rating_map.get("negative", 0)
        rated = positive + negative
        reason_distribution = {row["reason"] or "other": int(row["n"]) for row in reasons}
        return {
            "runs": total,
            "feedback_count": rated,
            "positive_count": positive,
            "negative_count": negative,
            "helpful_rate": round(positive / rated, 4) if rated else 0.0,
            "feedback_coverage": round(rated / total, 4) if total else 0.0,
            "negative_reason_distribution": reason_distribution,
            "rag_failure_share": round(reason_distribution.get("citation_failure", 0) / negative, 4)
            if negative else 0.0,
            "tool_failure_share": round(reason_distribution.get("tool_failure", 0) / negative, 4)
            if negative else 0.0,
            "median_latency_ms": run.get("median_latency_ms"),
            "p95_latency_ms": run.get("p95_latency_ms"),
            "latency_n": int(run["latency_n"] or 0),
            "avg_input_tokens": round(float(run["avg_input_tokens"]), 1)
            if run.get("avg_input_tokens") is not None else None,
            "avg_output_tokens": round(float(run["avg_output_tokens"]), 1)
            if run.get("avg_output_tokens") is not None else None,
            "unversioned_run_count": int(run["unversioned_runs"] or 0),
            "unversioned_run_rate": round(int(run["unversioned_runs"] or 0) / total, 4) if total else 0.0,
            "helpful_rate_by_prompt_version": [
                {
                    "prompt_version": row["prompt_version"], "positive_count": int(row["positive_count"]),
                    "feedback_count": int(row["feedback_count"]),
                    "rate": round(int(row["positive_count"]) / int(row["feedback_count"]), 4)
                    if int(row["feedback_count"]) else 0.0,
                }
                for row in trend
            ],
        }


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
        self._regenerations: dict[tuple[str, str], str | None] = {}
        self._feedback: dict[tuple[str, str], dict] = {}
        self._snapshots: dict[str, dict] = {}
        self._reviews: dict[str, dict] = {}
        self._review_events: list[dict] = []
        self._eval_cases: dict[str, dict] = {}
        self._audit: list[dict] = []

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
                       run_id, regenerated_from_message_id, status, metadata=None) -> dict:
        row = {
            "id": message_id, "thread_id": thread_id, "turn_id": turn_id,
            "user_id": user_id, "role": role, "content": content, "run_id": run_id,
            "regenerated_from_message_id": regenerated_from_message_id,
            "status": status, "created_at": _now(), "completed_at": None,
            "deleted_at": None, "metadata": metadata,
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

    def update_message_content(self, user_id, message_id, content, status, metadata=None) -> dict:
        row = self._messages.get(message_id)
        if row and row["user_id"] == user_id:
            row["content"] = content
            row["status"] = status
            row["completed_at"] = _now() if status == "completed" else None
            if metadata is not None:
                row["metadata"] = metadata
        return dict(row) if row and row["user_id"] == user_id else {}

    def update_message_run_id(self, user_id, message_id, run_id) -> dict:
        row = self._messages.get(message_id)
        if row and row["user_id"] == user_id:
            row["run_id"] = run_id
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

    def update_title(self, user_id, conversation_id, title) -> dict:
        row = self._conversations.get(conversation_id)
        if row and row["user_id"] == user_id:
            row["title"] = title
            row["updated_at"] = _now()
            return dict(row)
        return {}

    def clear_conversation(self, user_id, conversation_id) -> int:
        removed = 0
        # regeneration_keys 孤儿清理：message_id 指向将删 messages 的行一并移除，
        # 作用域限定为受影响的 thread。
        message_ids = {mid for mid, m in self._messages.items()
                       if m["thread_id"] == conversation_id and m["user_id"] == user_id}
        feedback_ids = [row["id"] for row in self._feedback.values()
                        if row["thread_id"] == conversation_id and row["user_id"] == user_id]
        for feedback_id in feedback_ids:
            self._snapshots.pop(feedback_id, None)
        for key, row in list(self._feedback.items()):
            if row["thread_id"] == conversation_id and row["user_id"] == user_id:
                self._feedback.pop(key, None)
        for mid in message_ids:
            for key, val in list(self._regenerations.items()):
                if val == mid:
                    self._regenerations.pop(key, None)
        # 删 turns（级联 messages）、runs、retrievals、tool_calls
        turn_ids = {tid for tid, t in self._turns.items()
                    if t["thread_id"] == conversation_id and t["user_id"] == user_id}
        # 先删 runs 及其 children
        run_ids = {rid for rid, r in self._runs.items()
                   if r["thread_id"] == conversation_id and r["user_id"] == user_id}
        for rid in run_ids:
            self._runs.pop(rid, None)
        for tid, r in list(self._retrievals.items()):
            if r["run_id"] in run_ids:
                self._retrievals.pop(tid, None)
        for tid, r in list(self._tool_calls.items()):
            if r["run_id"] in run_ids:
                self._tool_calls.pop(tid, None)
        # 删 messages（属于这些 turns / thread）
        for mid in [mid for mid, m in self._messages.items()
                    if m["thread_id"] == conversation_id and m["user_id"] == user_id]:
            self._messages.pop(mid, None)
        for tid in turn_ids:
            self._turns.pop(tid, None)
            removed += 1
        return removed

    def delete_conversation(self, user_id, conversation_id) -> bool:
        row = self._conversations.get(conversation_id)
        existed = row is not None and row["user_id"] == user_id
        if not existed:
            return False
        self.clear_conversation(user_id, conversation_id)
        self._conversations.pop(conversation_id, None)
        # legacy 映射清理
        for legacy, cid in list(self._legacy_map.items()):
            if cid == conversation_id:
                del self._legacy_map[legacy]
        return True

    def list_runs(self, user_id, thread_id) -> list[dict]:
        rows = [r for r in self._runs.values()
                if r["thread_id"] == thread_id and r["user_id"] == user_id]
        rows.sort(key=lambda r: (r.get("created_at", ""), r["id"]))
        return [dict(r) for r in rows]

    # ── runs ──

    def insert_run(self, run_id, user_id, thread_id, turn_id, message_id, module,
                   agent_id, model, prompt_version, agent_version, status,
                   effective_tools=None) -> dict:
        now = _now()
        row = {
            "id": run_id, "user_id": user_id, "thread_id": thread_id, "turn_id": turn_id,
            "message_id": message_id, "module": module, "agent_id": agent_id,
            "model": model, "prompt_version": prompt_version, "agent_version": agent_version,
            "status": status, "input_tokens": None, "output_tokens": None,
            "total_tokens": None, "latency_ms": None, "langsmith_run_id": None,
            "error_type": None, "error_code": None, "error_summary": None,
            "effective_tools": list(effective_tools) if effective_tools is not None else None,
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

    # ── regeneration idempotency ──

    def get_regeneration(self, user_id, key) -> str | None:
        return self._regenerations.get((user_id, key))

    def create_regeneration(self, user_id, key, message_id) -> str | None:
        k = (user_id, key)
        if k in self._regenerations:
            return None  # 冲突：已存在（路由据此复用首次结果）
        self._regenerations[k] = message_id
        return message_id

    def reserve_regeneration(self, user_id, key, message_id=None) -> tuple[str, str | None]:
        k = (user_id, key)
        if k in self._regenerations:
            mid = self._regenerations[k]
            return ("exists", mid)  # 已存在 → 其 message_id 或 None（进行中）
        self._regenerations[k] = message_id  # 预留，message_id 待回填（通常 None）
        return ("reserved", None)

    def complete_regeneration(self, user_id, key, message_id) -> str | None:
        k = (user_id, key)
        if k not in self._regenerations:
            return None
        self._regenerations[k] = message_id
        return message_id

    def release_regeneration(self, user_id, key) -> bool:
        k = (user_id, key)
        existed = k in self._regenerations
        self._regenerations.pop(k, None)
        return existed

    # ── retrievals / tool calls ──

    def insert_retrieval(self, retrieval_id, run_id, query_index, fields) -> dict:
        row = {"id": retrieval_id, "run_id": run_id, "query_index": query_index, **fields}
        self._retrievals[retrieval_id] = row
        return dict(row)

    def insert_tool_call(self, tool_call_id, run_id, tool_name, fields) -> dict:
        row = {"id": tool_call_id, "run_id": run_id, "tool_name": tool_name, **fields}
        self._tool_calls[tool_call_id] = row
        return dict(row)

    # ── feedback / privacy snapshots ──

    def upsert_feedback(self, user_id, fields) -> dict:
        key = (user_id, fields["message_id"])
        old = self._feedback.get(key)
        now = _now()
        row = {
            "id": (old or fields)["id"], "user_id": user_id,
            "thread_id": fields["thread_id"], "turn_id": fields["turn_id"],
            "message_id": fields["message_id"], "run_id": fields["run_id"],
            "rating": fields["rating"], "reason": fields.get("reason"),
            "comment": fields.get("comment"), "share_context": fields["share_context"],
            "created_at": (old or {}).get("created_at", now), "updated_at": now,
        }
        self._feedback[key] = row
        return dict(row)

    def list_feedback(self, user_id, thread_id) -> list[dict]:
        rows = [row for row in self._feedback.values()
                if row["user_id"] == user_id and row["thread_id"] == thread_id]
        rows.sort(key=lambda row: (row["updated_at"], row["id"]))
        return [dict(row) for row in rows]

    def upsert_feedback_snapshot(self, feedback_id, user_id, fields) -> dict:
        old = self._snapshots.get(feedback_id)
        row = {
            "id": (old or fields)["id"], "feedback_id": feedback_id, "user_id": user_id,
            "snapshot_json": fields["snapshot_json"], "redaction_version": fields["redaction_version"],
            "redaction_count": fields["redaction_count"], "expires_at": fields["expires_at"],
            "created_at": _now(),
        }
        self._snapshots[feedback_id] = row
        return dict(row)

    def delete_feedback_snapshot(self, feedback_id, user_id) -> bool:
        row = self._snapshots.get(feedback_id)
        if row is None or row["user_id"] != user_id:
            return False
        del self._snapshots[feedback_id]
        return True

    def delete_feedback(self, user_id, message_id) -> bool:
        row = self._feedback.pop((user_id, message_id), None)
        if row is None:
            return False
        self._snapshots.pop(row["id"], None)
        return True

    def insert_audit(self, actor_user_id, action, resource_type, resource_id, metadata) -> dict:
        row = {"id": str(uuid7()), "actor_user_id": actor_user_id, "action": action,
               "resource_type": resource_type, "resource_id": resource_id,
               "metadata": dict(metadata), "created_at": _now()}
        self._audit.append(row)
        return dict(row)

    def replace_feedback_with_snapshot(self, user_id, fields, snapshot_fields) -> dict:
        """Fake equivalent of the Postgres all-or-nothing consent write."""
        if fields["rating"] != "negative" or not fields["share_context"]:
            snapshot_fields = None
        with self.write_lock:
            key = (user_id, fields["message_id"])
            old = self._feedback.get(key)
            now = _now()
            feedback = {
                "id": (old or fields)["id"], "user_id": user_id,
                "thread_id": fields["thread_id"], "turn_id": fields["turn_id"],
                "message_id": fields["message_id"], "run_id": fields["run_id"],
                "rating": fields["rating"], "reason": fields.get("reason"),
                "comment": fields.get("comment"), "share_context": fields["share_context"],
                "created_at": (old or {}).get("created_at", now), "updated_at": now,
            }
            snapshot = None
            if snapshot_fields is not None:
                _json_dumps(snapshot_fields["snapshot_json"])
                existing = self._snapshots.get(feedback["id"])
                snapshot = {
                    "id": (existing or snapshot_fields)["id"], "feedback_id": feedback["id"], "user_id": user_id,
                    "snapshot_json": snapshot_fields["snapshot_json"],
                    "redaction_version": snapshot_fields["redaction_version"],
                    "redaction_count": snapshot_fields["redaction_count"],
                    "expires_at": snapshot_fields["expires_at"], "created_at": now,
                }
            self._feedback[key] = feedback
            if snapshot is None:
                self._snapshots.pop(feedback["id"], None)
            else:
                self._snapshots[feedback["id"]] = snapshot
            return dict(feedback)

    def delete_feedback_with_audit(self, user_id, message_id, metadata) -> bool:
        """Fake equivalent of the Postgres atomic deletion/audit transaction."""
        with self.write_lock:
            audit = {"id": str(uuid7()), "actor_user_id": user_id, "action": "feedback.deleted",
                     "resource_type": "message_feedback", "resource_id": message_id,
                     "metadata": dict(metadata), "created_at": _now()}
            _json_dumps(audit["metadata"])
            row = self._feedback.get((user_id, message_id))
            if audit["metadata"].get("deleted") is None:
                audit["metadata"]["deleted"] = row is not None
            if row is not None:
                del self._feedback[(user_id, message_id)]
                self._snapshots.pop(row["id"], None)
            self._audit.append(audit)
            return row is not None

    # ── quality reviewer read models ──

    @staticmethod
    def _quality_feedback_row(feedback: dict, snapshot: dict | None) -> dict:
        run = feedback["run"]
        review = feedback.get("review")
        return {
            "feedback_id": feedback["id"], "run_id": feedback["run_id"], "reason": feedback.get("reason"),
            "share_context": feedback["share_context"], "created_at": feedback["created_at"],
            "updated_at": feedback["updated_at"], "module": run["module"], "agent_id": run["agent_id"],
            "model": run["model"], "prompt_version": run["prompt_version"], "agent_version": run["agent_version"],
            "status": run["status"], "input_tokens": run.get("input_tokens"),
            "output_tokens": run.get("output_tokens"), "total_tokens": run.get("total_tokens"),
            "latency_ms": run.get("latency_ms"), "error_type": run.get("error_type"),
            "error_code": run.get("error_code"),
            "review_status": (review or {}).get("status"), "root_cause": (review or {}).get("root_cause"),
            "snapshot_available": bool(snapshot and _snapshot_active(snapshot)),
        }

    def list_quality_feedback(self) -> list[dict]:
        rows = []
        for feedback in self._feedback.values():
            if feedback["rating"] != "negative":
                continue
            run = self._runs.get(feedback["run_id"])
            if run is None or run.get("user_id") != feedback["user_id"]:
                continue
            row = dict(feedback)
            row["run"] = run
            row["review"] = self._reviews.get(feedback["id"])
            rows.append(self._quality_feedback_row(row, self._snapshots.get(feedback["id"])))
        return sorted(rows, key=lambda row: (row["updated_at"], row["feedback_id"]), reverse=True)

    def get_quality_feedback(self, feedback_id) -> dict | None:
        for feedback in self._feedback.values():
            if feedback["id"] != feedback_id or feedback["rating"] != "negative":
                continue
            run = self._runs.get(feedback["run_id"])
            if run is None or run.get("user_id") != feedback["user_id"]:
                return None
            row = dict(feedback)
            row["run"] = run
            row["review"] = self._reviews.get(feedback["id"])
            return self._quality_feedback_row(row, self._snapshots.get(feedback["id"]))
        return None

    def get_quality_snapshot(self, feedback_id) -> dict | None:
        for feedback in self._feedback.values():
            if feedback["id"] == feedback_id and feedback["rating"] == "negative":
                snapshot = self._snapshots.get(feedback_id)
                if snapshot and _snapshot_active(snapshot):
                    return {
                        "snapshot_id": snapshot["id"], "snapshot_json": snapshot["snapshot_json"],
                        "redaction_version": snapshot["redaction_version"], "redaction_count": snapshot["redaction_count"],
                        "expires_at": snapshot["expires_at"], "created_at": snapshot["created_at"],
                    }
        return None

    def get_quality_diagnostics(self, feedback_id) -> dict | None:
        feedback = next((row for row in self._feedback.values()
                         if row["id"] == feedback_id and row["rating"] == "negative"), None)
        if feedback is None:
            return None
        run = self._runs.get(feedback["run_id"])
        if run is None or run.get("user_id") != feedback["user_id"]:
            return None
        run_fields = (
            "id", "module", "agent_id", "model", "prompt_version", "agent_version", "status", "input_tokens",
            "output_tokens", "total_tokens", "latency_ms", "error_type", "error_code", "effective_tools",
            "started_at", "finished_at", "created_at",
        )
        retrieval_fields = (
            "document_id", "chunk_id", "recall_score", "rerank_score", "rank_before", "rank_after",
            "used_in_final_context", "retrieval_source",
        )
        tool_fields = ("tool_name", "status", "duration_ms", "requires_hitl", "hitl_status", "error_type")
        return {
            "run": {("run_id" if key == "id" else key): run.get(key) for key in run_fields},
            "retrievals": [{key: row.get(key) for key in retrieval_fields}
                           for row in self._retrievals.values() if row["run_id"] == run["id"]],
            "tool_calls": [{key: row.get(key) for key in tool_fields}
                           for row in self._tool_calls.values() if row["run_id"] == run["id"]],
        }

    # ── feedback reviews（人工归因）──

    def get_feedback_review(self, feedback_id) -> dict | None:
        review = self._reviews.get(feedback_id)
        if review is None:
            return None
        return {
            "id": review["id"], "feedback_id": review["feedback_id"],
            "reviewer_user_id": review["reviewer_user_id"], "root_cause": review["root_cause"],
            "review_status": review["status"], "reviewer_note": review["reviewer_note"],
            "created_at": review["created_at"], "updated_at": review["updated_at"],
        }

    def upsert_feedback_review(self, fields, events, audits) -> dict:
        """Fake equivalent of the Postgres atomic review+events+audit write."""
        with self.write_lock:
            row = dict(fields)
            existing = self._reviews.get(fields["feedback_id"])
            row["created_at"] = fields["created_at"]
            if existing:
                row["created_at"] = existing.get("created_at", row["created_at"])
            self._reviews[fields["feedback_id"]] = dict(row)
            for event in events:
                stored_event = dict(event)
                stored_event["feedback_id"] = fields["feedback_id"]
                self._review_events.append(stored_event)
            for audit in audits:
                _json_dumps(audit["metadata"])
                self._audit.append(dict(audit))
        return {
            "id": row["id"], "feedback_id": row["feedback_id"], "reviewer_user_id": row["reviewer_user_id"],
            "root_cause": row["root_cause"], "review_status": row["status"],
            "reviewer_note": row["reviewer_note"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    # ── eval cases（Phase 6，§29）──

    def list_eval_cases(self, status=None) -> list[dict]:
        rows = [dict(r) for r in self._eval_cases.values()]
        if status:
            rows = [r for r in rows if r["status"] == status]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    def get_eval_case(self, case_id) -> dict | None:
        row = self._eval_cases.get(case_id)
        return dict(row) if row else None

    def insert_eval_case(self, fields, audits) -> dict:
        with self.write_lock:
            row = dict(fields)
            self._eval_cases[fields["id"]] = dict(row)
            for audit in audits:
                _json_dumps(audit["metadata"])
                self._audit.append(dict(audit))
        return dict(row)

    def update_eval_case(self, case_id, fields, audits) -> dict:
        with self.write_lock:
            existing = self._eval_cases.get(case_id)
            if existing is None:
                raise KeyError(f"eval case {case_id!r} 不存在")
            merged = dict(existing)
            for key in ("status", "target_agent", "input_text", "context", "expected_behavior",
                        "rubric", "failure_reason", "source_model", "source_prompt_version",
                        "source_agent_version", "approved_by", "approved_at", "updated_at"):
                if key in fields:
                    merged[key] = fields[key]
            self._eval_cases[case_id] = merged
            for audit in audits:
                _json_dumps(audit["metadata"])
                self._audit.append(dict(audit))
        return dict(merged)

    @staticmethod
    def _run_in_scope(run: dict, filters: dict) -> bool:
        if filters.get("from_dt") is not None and (run.get("started_at") or "") < filters["from_dt"]:
            return False
        if filters.get("to_dt") is not None and (run.get("started_at") or "") >= filters["to_dt"]:
            return False
        for key in ("module", "agent", "model", "prompt_version", "agent_version"):
            value = filters.get(key)
            if value and run.get({"agent": "agent_id"}.get(key, key)) != value:
                return False
        return True

    def compute_quality_metrics(self, filters: dict) -> dict:
        runs = [r for r in self._runs.values() if self._run_in_scope(r, filters)]
        feedback = [f for f in self._feedback.values() if self._runs.get(f["run_id"]) in runs]
        positive = sum(1 for f in feedback if f["rating"] == "positive")
        negative = sum(1 for f in feedback if f["rating"] == "negative")
        rated = positive + negative
        total = len(runs)
        latency = sorted(r["latency_ms"] for r in runs if r.get("latency_ms") is not None)
        reason_distribution: dict[str, int] = {}
        for f in feedback:
            if f["rating"] == "negative":
                reason = f.get("reason") or "other"
                reason_distribution[reason] = reason_distribution.get(reason, 0) + 1

        def percentile(values: list, p: float) -> float | None:
            if not values:
                return None
            index = (len(values) - 1) * p
            lower = int(index)
            upper = min(lower + 1, len(values) - 1)
            return values[lower] if lower == upper else (values[lower] + values[upper]) / 2

        unversioned = sum(
            1 for r in runs
            if not (r.get("prompt_version") and r.get("prompt_version") != "unversioned")
            or not (r.get("agent_version") and r.get("agent_version") != "unversioned")
        )
        token_runs = [r for r in runs if r.get("input_tokens") is not None or r.get("output_tokens") is not None]
        avg_in = round(sum(r.get("input_tokens") or 0 for r in token_runs) / len(token_runs), 1) if token_runs else None
        avg_out = round(sum(r.get("output_tokens") or 0 for r in token_runs) / len(token_runs), 1) if token_runs else None
        versions: dict[str, dict] = {}
        for f in feedback:
            run = self._runs.get(f["run_id"])
            if not run:
                continue
            version = run.get("prompt_version") or ""
            entry = versions.setdefault(version, {"positive_count": 0, "feedback_count": 0})
            entry["feedback_count"] += 1
            if f["rating"] == "positive":
                entry["positive_count"] += 1
        return {
            "runs": total,
            "feedback_count": rated,
            "positive_count": positive,
            "negative_count": negative,
            "helpful_rate": round(positive / rated, 4) if rated else 0.0,
            "feedback_coverage": round(rated / total, 4) if total else 0.0,
            "negative_reason_distribution": reason_distribution,
            "rag_failure_share": round(reason_distribution.get("citation_failure", 0) / negative, 4)
            if negative else 0.0,
            "tool_failure_share": round(reason_distribution.get("tool_failure", 0) / negative, 4)
            if negative else 0.0,
            "median_latency_ms": percentile(latency, 0.5),
            "p95_latency_ms": percentile(latency, 0.95),
            "latency_n": len(latency),
            "avg_input_tokens": avg_in,
            "avg_output_tokens": avg_out,
            "unversioned_run_count": unversioned,
            "unversioned_run_rate": round(unversioned / total, 4) if total else 0.0,
            "helpful_rate_by_prompt_version": [
                {
                    "prompt_version": version or "unversioned",
                    "positive_count": entry["positive_count"], "feedback_count": entry["feedback_count"],
                    "rate": round(entry["positive_count"] / entry["feedback_count"], 4)
                    if entry["feedback_count"] else 0.0,
                }
                for version, entry in sorted(versions.items())
            ],
        }


def create_conversation_db(settings) -> ConversationDb:
    """按配置创建对话库：Postgres（唯一生产后端）或 Fake（仅测试 backend=fake）。"""
    backend = getattr(settings.vector_store, "backend", "")
    dsn = (settings.memory.postgres.dsn or "").strip()
    if backend == "fake":
        return FakeConversationDb()
    if not dsn:
        raise ValueError("memory.postgres.dsn 未设置（生产环境对话库必须使用 Postgres）")
    return PostgresConversationDb(dsn)
