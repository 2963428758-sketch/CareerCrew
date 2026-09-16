"""Human-governed operations for the evolvable long-term memory records.

The automatic memory writer remains in :mod:`memory.service`.  This module is
the deliberately smaller boundary used by the management API: every mutation
is owner-scoped, optimistic-lock protected, and appended to an immutable event
stream.  The FakeMemoryDb path mirrors the PostgreSQL path so API/unit tests do
not need a live database.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any, Literal

from careercrew_core.memory.records import LongTermMemoryRepository, canonical_hash, now_iso

MemoryAction = Literal["confirm", "edit", "ignore", "expire"]
_ACTIONS = frozenset({"confirm", "edit", "ignore", "expire"})
_ACTIVE_STATUS = "active"
_GOVERNABLE_STATUS = frozenset({"active"})
_MAX_REASON_LENGTH = 500
_MAX_DISPLAY_LENGTH = 20_000


class MemoryGovernanceError(RuntimeError):
    """Base error for a rejected management operation."""


class MemoryNotFoundError(MemoryGovernanceError):
    """The authenticated owner cannot access the requested record."""


class MemoryConflictError(MemoryGovernanceError):
    """The supplied optimistic-lock version is stale or the state changed."""


class MemoryValidationError(MemoryGovernanceError):
    """The requested state transition or value is not valid."""


def _require_reason(reason: str) -> str:
    value = str(reason or "").strip()
    if len(value) > _MAX_REASON_LENGTH:
        raise MemoryValidationError("操作原因不能超过 500 个字符")
    return value


def _require_display_text(display_text: str | None) -> str:
    value = str(display_text or "").strip()
    if not value:
        raise MemoryValidationError("修改内容不能为空")
    if len(value) > _MAX_DISPLAY_LENGTH:
        raise MemoryValidationError("修改内容过长")
    return value


def _validate_json_value(value: Any) -> Any:
    """Ensure an edited value can be persisted as JSON without leaking it in logs."""
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError("修改值必须是可保存的 JSON") from exc
    return value


def _snapshot(record: dict[str, Any] | None) -> dict[str, Any]:
    """Build an audit-safe snapshot without copying memory text or payload."""
    if not record:
        return {}
    display = str(record.get("display_text") or "")
    snapshot: dict[str, Any] = {
        "id": str(record.get("id") or ""),
        "user_id": str(record.get("user_id") or ""),
        "memory_type": str(record.get("memory_type") or ""),
        "category": str(record.get("category") or ""),
        "normalized_key": str(record.get("normalized_key") or ""),
        "canonical_hash": str(record.get("canonical_hash") or ""),
        "display_text_hash": canonical_hash(display),
        "display_text_length": len(display),
        "status": str(record.get("status") or ""),
        "row_version": int(record.get("row_version") or 0),
    }
    return snapshot


def _public_value(value: Any) -> Any:
    """Convert DB-driver scalar values into JSON-compatible response values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _public_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    return value


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _public_value(value) for key, value in record.items()}


class MemoryGovernance:
    """Owner-scoped memory correction and history service."""

    def __init__(self, db) -> None:
        self.db = db
        self.repo = LongTermMemoryRepository(db)

    @property
    def _fake(self) -> bool:
        return self.repo._fake

    def _fake_state(self) -> dict[str, Any]:
        state = self.repo._fake_state()
        state.setdefault("events", {})
        return state

    def get(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        if self._fake:
            record = self._fake_state()["records"].get(memory_id)
            if not record or record.get("user_id") != user_id:
                return None
            return dict(record)
        return self._get_pg(user_id, memory_id)

    def _require(self, user_id: str, memory_id: str) -> dict[str, Any]:
        if self._fake:
            record = self._fake_state()["records"].get(memory_id)
            if not record or record.get("user_id") != user_id:
                raise MemoryNotFoundError("记忆不存在或无权访问")
            # Mutating operations need the state-owned row; public ``get`` still
            # returns a copy to keep callers from changing state accidentally.
            return record
        record = self.get(user_id, memory_id)
        if not record:
            # Deliberately collapse missing and cross-owner IDs into one result.
            raise MemoryNotFoundError("记忆不存在或无权访问")
        return record

    def list_records(
        self,
        user_id: str,
        *,
        status: str = "active",
        category: str = "",
        query: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if status not in {"active", "all"}:
            raise MemoryValidationError("status 必须为 active 或 all")
        limit = max(1, min(int(limit), 100))
        needle = str(query or "").strip().casefold()
        if self._fake:
            rows = [
                dict(row)
                for row in self._fake_state()["records"].values()
                if row.get("user_id") == user_id
                and (status == "all" or row.get("status") == _ACTIVE_STATUS)
                and (not category or row.get("category") == category)
                and (
                    not needle
                    or needle in str(row.get("display_text") or "").casefold()
                    or needle in str(row.get("normalized_key") or "").casefold()
                )
            ]
            rows.sort(key=lambda row: (str(row.get("updated_at") or ""), str(row.get("id") or "")), reverse=True)
            return [_public_record(row) for row in rows[:limit]]

        def _list(conn):
            sql = """
                SELECT mr.id::text AS id, mr.user_id, mr.memory_type, mr.category,
                       mr.scope_type, mr.scope_key, mr.capture_mode, mr.normalized_key,
                       mr.cardinality, mr.canonical_hash, mr.display_text,
                       mr.confidence, mr.importance, mr.source_quality, mr.sensitivity,
                       mr.lifecycle_class, mr.valid_from, mr.valid_until,
                       mr.last_confirmed_at, mr.last_accessed_at, mr.access_count,
                       mr.status, mr.schema_version, mr.row_version,
                       mr.created_at, mr.updated_at,
                       COALESCE(sv.normalized_value, ee.event_payload, '{}'::jsonb) AS payload
                FROM memory_records mr
                LEFT JOIN memory_semantic_values sv ON sv.memory_id = mr.id
                LEFT JOIN memory_episodic_events ee ON ee.memory_id = mr.id
                WHERE mr.user_id=%s
            """
            params: list[Any] = [user_id]
            if status == "active":
                sql += " AND mr.status='active' AND (mr.valid_until IS NULL OR mr.valid_until > now())"
            if category:
                sql += " AND mr.category=%s"
                params.append(category)
            if needle:
                # pg_trgm indexes remain useful for the two text columns; the
                # value is still parameterized and owner-scoped.
                sql += " AND (mr.display_text ILIKE %s OR mr.normalized_key ILIKE %s)"
                pattern = f"%{query.strip()}%"
                params.extend([pattern, pattern])
            sql += " ORDER BY mr.updated_at DESC, mr.id DESC LIMIT %s"
            params.append(limit)
            return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]

        return [_public_record(row) for row in self.repo._pg(_list)]

    def apply_action(
        self,
        user_id: str,
        memory_id: str,
        *,
        action: MemoryAction | str,
        expected_row_version: int,
        display_text: str | None = None,
        value: Any = None,
        reason: str = "",
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        if action not in _ACTIONS:
            raise MemoryValidationError("不支持的记忆操作")
        if int(expected_row_version) < 1:
            raise MemoryValidationError("row_version 必须为正整数")
        reason = _require_reason(reason)
        actor_id = str(actor_id or user_id)
        if action == "edit":
            return self._edit(
                user_id,
                memory_id,
                expected_row_version=int(expected_row_version),
                display_text=display_text,
                value=value,
                reason=reason,
                actor_id=actor_id,
            )
        return self._status_change(
            user_id,
            memory_id,
            action=action,
            expected_row_version=int(expected_row_version),
            reason=reason,
            actor_id=actor_id,
        )

    def _check_active(self, record: dict[str, Any]) -> None:
        if record.get("status") not in _GOVERNABLE_STATUS:
            raise MemoryValidationError("只有 active 记忆可以执行此操作")

    def _check_version(self, record: dict[str, Any], expected: int) -> None:
        current = int(record.get("row_version") or 0)
        if current != expected:
            raise MemoryConflictError("记忆已被其他操作更新，请刷新后重试")

    def _append_fake_event(
        self,
        *,
        user_id: str,
        memory_id: str,
        action: str,
        reason: str,
        actor_id: str,
        before: dict[str, Any],
        after: dict[str, Any],
        row_version: int,
    ) -> dict[str, Any]:
        event = {
            "id": str(uuid.uuid4()),
            "owner_id": user_id,
            "memory_id": memory_id,
            "action": action,
            "reason": reason,
            "actor_id": actor_id,
            "before_snapshot": before,
            "after_snapshot": after,
            "row_version": row_version,
            "created_at": now_iso(),
        }
        self._fake_state()["events"][event["id"]] = event
        return event

    def _status_change(
        self,
        user_id: str,
        memory_id: str,
        *,
        action: str,
        expected_row_version: int,
        reason: str,
        actor_id: str,
    ) -> dict[str, Any]:
        if self._fake:
            record = self._require(user_id, memory_id)
            self._check_active(record)
            self._check_version(record, expected_row_version)
            before = _snapshot(record)
            record["status"] = {
                "confirm": "active",
                "ignore": "ignored",
                "expire": "expired",
            }[action]
            record["row_version"] = expected_row_version + 1
            record["updated_at"] = now_iso()
            if action == "confirm":
                record["last_confirmed_at"] = record["updated_at"]
            else:
                self.repo.enqueue_vector(memory_id, user_id, "delete")
            after = _snapshot(record)
            event = self._append_fake_event(
                user_id=user_id, memory_id=memory_id, action=action, reason=reason,
                actor_id=actor_id, before=before, after=after,
                row_version=record["row_version"],
            )
            result = _public_record(record)
            result["event_id"] = event["id"]
            return result

        def _write(conn):
            record = self._get_pg(user_id, memory_id, conn=conn, for_update=True)
            if not record:
                raise MemoryNotFoundError("记忆不存在或无权访问")
            self._check_active(record)
            self._check_version(record, expected_row_version)
            before = _snapshot(record)
            new_status = {"confirm": "active", "ignore": "ignored", "expire": "expired"}[action]
            if action == "confirm":
                sql = """
                    UPDATE memory_records
                    SET last_confirmed_at=now(), updated_at=now(), row_version=row_version+1
                    WHERE id=%s AND user_id=%s AND row_version=%s AND status='active'
                """
            else:
                sql = """
                    UPDATE memory_records
                    SET status=%s, updated_at=now(), row_version=row_version+1
                    WHERE id=%s AND user_id=%s AND row_version=%s AND status='active'
                """
            params = (
                (memory_id, user_id, expected_row_version)
                if action == "confirm"
                else (new_status, memory_id, user_id, expected_row_version)
            )
            changed = conn.execute(sql, params).rowcount or 0
            if changed != 1:
                raise MemoryConflictError("记忆已被其他操作更新，请刷新后重试")
            if action != "confirm":
                self.repo._enqueue_vector_pg(conn, memory_id, user_id, "delete")
            after_record = self._get_pg(user_id, memory_id, conn=conn)
            event = self._append_pg_event(
                conn, user_id=user_id, memory_id=memory_id, action=action,
                reason=reason, actor_id=actor_id, before=before,
                after=_snapshot(after_record), row_version=int(after_record["row_version"]),
            )
            result = _public_record(after_record)
            result["event_id"] = event["id"]
            return result

        return self.repo._pg(_write)

    def _edited_payload(self, record: dict[str, Any], display_text: str, value: Any) -> tuple[str, dict[str, Any]]:
        payload = dict(record.get("payload") or {}) if isinstance(record.get("payload"), dict) else {}
        new_value = display_text if value is None else _validate_json_value(value)
        payload["value"] = new_value
        return canonical_hash(new_value), payload

    def _edit(
        self,
        user_id: str,
        memory_id: str,
        *,
        expected_row_version: int,
        display_text: str | None,
        value: Any,
        reason: str,
        actor_id: str,
    ) -> dict[str, Any]:
        text = _require_display_text(display_text)
        if self._fake:
            old = self._require(user_id, memory_id)
            self._check_active(old)
            self._check_version(old, expected_row_version)
            new_hash, payload = self._edited_payload(old, text, value)
            before = _snapshot(old)
            old["status"] = "superseded"
            old["row_version"] = expected_row_version + 1
            old["updated_at"] = now_iso()
            new = dict(old)
            new.update({
                "id": str(uuid.uuid4()), "canonical_hash": new_hash,
                "display_text": text, "payload": payload, "status": "active",
                "row_version": 1, "created_at": now_iso(), "updated_at": now_iso(),
                "last_confirmed_at": now_iso(), "capture_mode": "explicit",
            })
            self._fake_state()["records"][new["id"]] = new
            self.repo.add_relation(new["id"], memory_id, "supersedes")
            self.repo.add_source(new["id"], "manual_edit", {"actor_id": actor_id})
            self.repo.enqueue_vector(memory_id, user_id, "delete")
            self.repo.enqueue_vector(new["id"], user_id, "upsert")
            event = self._append_fake_event(
                user_id=user_id, memory_id=new["id"], action="edit", reason=reason,
                actor_id=actor_id, before=before, after=_snapshot(new), row_version=1,
            )
            result = _public_record(new)
            result["event_id"] = event["id"]
            return result

        def _write(conn):
            old = self._get_pg(user_id, memory_id, conn=conn, for_update=True)
            if not old:
                raise MemoryNotFoundError("记忆不存在或无权访问")
            self._check_active(old)
            self._check_version(old, expected_row_version)
            new_hash, payload = self._edited_payload(old, text, value)
            before = _snapshot(old)
            changed = conn.execute(
                "UPDATE memory_records SET status='superseded',updated_at=now(),row_version=row_version+1 "
                "WHERE id=%s AND user_id=%s AND row_version=%s AND status='active'",
                (memory_id, user_id, expected_row_version),
            ).rowcount or 0
            if changed != 1:
                raise MemoryConflictError("记忆已被其他操作更新，请刷新后重试")
            new_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO memory_records (
                    id,user_id,memory_type,category,scope_type,scope_key,capture_mode,
                    normalized_key,cardinality,canonical_hash,display_text,confidence,
                    importance,source_quality,sensitivity,lifecycle_class,valid_from,
                    last_confirmed_at,status,schema_version,row_version,created_at,updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,'explicit',%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now(),
                          'active',%s,1,now(),now())
                """,
                (
                    new_id, user_id, old["memory_type"], old["category"],
                    old.get("scope_type") or "global", old.get("scope_key"),
                    old.get("normalized_key"), old.get("cardinality") or "single",
                    new_hash, text, old.get("confidence", 1.0), old.get("importance", 0.5),
                    old.get("source_quality", 1.0), old.get("sensitivity") or "normal",
                    old.get("lifecycle_class") or "long_lived", old.get("schema_version", 1),
                ),
            )
            if old["memory_type"] == "semantic":
                conn.execute(
                    "INSERT INTO memory_semantic_values (memory_id,normalized_value,value_hash) VALUES (%s,%s::jsonb,%s)",
                    (new_id, json.dumps(payload.get("value"), ensure_ascii=False), new_hash),
                )
            else:
                old_event = conn.execute(
                    "SELECT event_type,occurred_at,event_payload FROM memory_episodic_events WHERE memory_id=%s",
                    (memory_id,),
                ).fetchone()
                if old_event:
                    conn.execute(
                        "INSERT INTO memory_episodic_events (memory_id,event_type,occurred_at,event_payload) VALUES (%s,%s,%s,%s::jsonb)",
                        (new_id, old_event["event_type"], old_event["occurred_at"], json.dumps(payload.get("value"), ensure_ascii=False)),
                    )
            conn.execute(
                "INSERT INTO memory_relations (id,from_memory_id,to_memory_id,relation_type,metadata) VALUES (%s,%s,%s,'supersedes',%s::jsonb)",
                (str(uuid.uuid4()), new_id, memory_id, json.dumps({"actor_id": actor_id})),
            )
            conn.execute(
                "INSERT INTO memory_sources (id,memory_id,source_type,source_excerpt_redacted,asserted_by) VALUES (%s,%s,'manual_edit',%s,%s)",
                (str(uuid.uuid4()), new_id, "manual edit", actor_id),
            )
            self.repo._enqueue_vector_pg(conn, memory_id, user_id, "delete")
            self.repo._enqueue_vector_pg(conn, new_id, user_id, "upsert")
            new_record = self._get_pg(user_id, new_id, conn=conn)
            event = self._append_pg_event(
                conn, user_id=user_id, memory_id=new_id, action="edit", reason=reason,
                actor_id=actor_id, before=before, after=_snapshot(new_record), row_version=1,
            )
            result = _public_record(new_record)
            result["event_id"] = event["id"]
            return result

        return self.repo._pg(_write)

    def merge(
        self,
        user_id: str,
        memory_id: str,
        other_memory_id: str,
        *,
        expected_row_version: int,
        other_row_version: int,
        reason: str = "",
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        if memory_id == other_memory_id:
            raise MemoryValidationError("不能把记忆合并到自身")
        reason = _require_reason(reason)
        actor_id = str(actor_id or user_id)
        if self._fake:
            target = self._require(user_id, memory_id)
            other = self._require(user_id, other_memory_id)
            self._check_active(target)
            self._check_active(other)
            if target.get("memory_type") != other.get("memory_type"):
                raise MemoryValidationError("只能合并相同类型的记忆")
            self._check_version(target, expected_row_version)
            self._check_version(other, other_row_version)
            before = _snapshot(target)
            target["row_version"] = expected_row_version + 1
            target["updated_at"] = now_iso()
            other["status"] = "superseded"
            other["row_version"] = other_row_version + 1
            other["updated_at"] = now_iso()
            self.repo.add_relation(memory_id, other_memory_id, "consolidates")
            self.repo.enqueue_vector(other_memory_id, user_id, "delete")
            self.repo.enqueue_vector(memory_id, user_id, "upsert")
            event = self._append_fake_event(
                user_id=user_id, memory_id=memory_id, action="merge", reason=reason,
                actor_id=actor_id, before=before, after=_snapshot(target),
                row_version=target["row_version"],
            )
            result = _public_record(target)
            result["event_id"] = event["id"]
            return result

        def _write(conn):
            records = self._get_pg_many(
                conn, user_id, [memory_id, other_memory_id], for_update=True,
            )
            target = records.get(memory_id)
            other = records.get(other_memory_id)
            if not target or not other:
                raise MemoryNotFoundError("记忆不存在或无权访问")
            self._check_active(target)
            self._check_active(other)
            if target.get("memory_type") != other.get("memory_type"):
                raise MemoryValidationError("只能合并相同类型的记忆")
            self._check_version(target, expected_row_version)
            self._check_version(other, other_row_version)
            before = _snapshot(target)
            changed = conn.execute(
                "UPDATE memory_records SET row_version=row_version+1,updated_at=now() WHERE id=%s AND user_id=%s AND row_version=%s AND status='active'",
                (memory_id, user_id, expected_row_version),
            ).rowcount or 0
            if changed != 1:
                raise MemoryConflictError("记忆已被其他操作更新，请刷新后重试")
            changed = conn.execute(
                "UPDATE memory_records SET status='superseded',row_version=row_version+1,updated_at=now() WHERE id=%s AND user_id=%s AND row_version=%s AND status='active'",
                (other_memory_id, user_id, other_row_version),
            ).rowcount or 0
            if changed != 1:
                raise MemoryConflictError("待合并记忆已被其他操作更新，请刷新后重试")
            conn.execute(
                "INSERT INTO memory_relations (id,from_memory_id,to_memory_id,relation_type,metadata) VALUES (%s,%s,%s,'consolidates',%s::jsonb)",
                (str(uuid.uuid4()), memory_id, other_memory_id, json.dumps({"actor_id": actor_id})),
            )
            self.repo._enqueue_vector_pg(conn, other_memory_id, user_id, "delete")
            self.repo._enqueue_vector_pg(conn, memory_id, user_id, "upsert")
            after = self._get_pg(user_id, memory_id, conn=conn)
            event = self._append_pg_event(
                conn, user_id=user_id, memory_id=memory_id, action="merge", reason=reason,
                actor_id=actor_id, before=before, after=_snapshot(after),
                row_version=int(after["row_version"]),
            )
            result = _public_record(after)
            result["event_id"] = event["id"]
            return result

        return self.repo._pg(_write)

    def history(self, user_id: str, memory_id: str) -> dict[str, Any]:
        self._require(user_id, memory_id)
        if self._fake:
            state = self._fake_state()
            related = {memory_id}
            changed = True
            while changed:
                changed = False
                for relation in state["relations"].values():
                    if relation.get("from_memory_id") in related or relation.get("to_memory_id") in related:
                        before = len(related)
                        related.update({relation.get("from_memory_id"), relation.get("to_memory_id")})
                        related.discard(None)
                        changed = len(related) != before
            records = [
                _public_record(row) for row in state["records"].values()
                if row.get("user_id") == user_id and row.get("id") in related
            ]
            records.sort(key=lambda row: (str(row.get("updated_at") or ""), str(row.get("id") or "")), reverse=True)
            events = [
                _public_record(event) for event in state["events"].values()
                if event.get("owner_id") == user_id and event.get("memory_id") in related
            ]
            events.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
            relations = [
                _public_record(relation) for relation in state["relations"].values()
                if relation.get("from_memory_id") in related or relation.get("to_memory_id") in related
            ]
            sources = [
                {**_public_record(source), "memory_id": memory_id}
                for record_id, values in state["sources"].items()
                if record_id in related
                for source in values
            ]
            return {"records": records, "events": events, "relations": relations, "sources": sources}

        def _read(conn):
            relation_rows = conn.execute(
                """
                SELECT r.from_memory_id::text AS from_memory_id,
                       r.to_memory_id::text AS to_memory_id,
                       r.relation_type, r.confidence, r.metadata, r.created_at
                FROM memory_relations r
                JOIN memory_records f ON f.id=r.from_memory_id AND f.user_id=%s
                JOIN memory_records t ON t.id=r.to_memory_id AND t.user_id=%s
                WHERE r.from_memory_id=%s OR r.to_memory_id=%s
                ORDER BY r.created_at DESC
                """,
                (user_id, user_id, memory_id, memory_id),
            ).fetchall()
            related = {memory_id}
            relations = [dict(row) for row in relation_rows]
            for relation in relations:
                related.update({str(relation["from_memory_id"]), str(relation["to_memory_id"])})
            placeholders = ",".join(["%s"] * len(related))
            records = [dict(row) for row in conn.execute(
                f"""SELECT mr.id::text AS id,mr.user_id,mr.memory_type,mr.category,mr.normalized_key,
                    mr.display_text,mr.confidence,mr.importance,mr.source_quality,mr.status,
                    mr.row_version,mr.created_at,mr.updated_at,
                    COALESCE(sv.normalized_value,ee.event_payload,'{{}}'::jsonb) AS payload
                    FROM memory_records mr
                    LEFT JOIN memory_semantic_values sv ON sv.memory_id=mr.id
                    LEFT JOIN memory_episodic_events ee ON ee.memory_id=mr.id
                    WHERE mr.user_id=%s AND mr.id IN ({placeholders})
                    ORDER BY mr.updated_at DESC,mr.id DESC""",
                tuple([user_id, *related]),
            ).fetchall()]
            events = [dict(row) for row in conn.execute(
                f"SELECT id::text AS id,owner_id,memory_id::text AS memory_id,action,reason,actor_id,before_snapshot,after_snapshot,row_version,created_at FROM memory_record_events WHERE owner_id=%s AND memory_id IN ({placeholders}) ORDER BY created_at DESC",
                tuple([user_id, *related]),
            ).fetchall()]
            source_rows = [dict(row) for row in conn.execute(
                f"SELECT id::text AS id,memory_id::text AS memory_id,source_type,source_excerpt_redacted,asserted_by,evidence_strength,observed_at FROM memory_sources WHERE memory_id IN ({placeholders}) ORDER BY observed_at DESC",
                tuple(related),
            ).fetchall()]
            return {
                "records": [_public_record(row) for row in records],
                "events": [_public_record(row) for row in events],
                "relations": [_public_record(row) for row in relations],
                "sources": [_public_record(row) for row in source_rows],
            }

        return self.repo._pg(_read)

    # ── PostgreSQL helpers ────────────────────────────────────────────────

    @staticmethod
    def _record_select(for_update: bool = False) -> str:
        suffix = " FOR UPDATE OF mr" if for_update else ""
        return f"""
            SELECT mr.id::text AS id, mr.user_id, mr.memory_type, mr.category,
                   mr.scope_type, mr.scope_key, mr.capture_mode, mr.normalized_key,
                   mr.cardinality, mr.canonical_hash, mr.display_text,
                   mr.confidence, mr.importance, mr.source_quality, mr.sensitivity,
                   mr.lifecycle_class, mr.valid_from, mr.valid_until,
                   mr.last_confirmed_at, mr.last_accessed_at, mr.access_count,
                   mr.status, mr.schema_version, mr.row_version,
                   mr.created_at, mr.updated_at,
                   COALESCE(sv.normalized_value, ee.event_payload, '{{}}'::jsonb) AS payload
            FROM memory_records mr
            LEFT JOIN memory_semantic_values sv ON sv.memory_id = mr.id
            LEFT JOIN memory_episodic_events ee ON ee.memory_id = mr.id
            WHERE mr.user_id=%s AND mr.id=%s{suffix}
        """

    def _get_pg(self, user_id: str, memory_id: str, *, conn=None, for_update: bool = False) -> dict[str, Any] | None:
        def _read(connection):
            row = connection.execute(
                self._record_select(for_update), (user_id, memory_id),
            ).fetchone()
            return dict(row) if row else None
        if conn is not None:
            return _read(conn)
        return self.repo._pg(_read)

    def _get_pg_many(self, conn, user_id: str, memory_ids: list[str], *, for_update: bool) -> dict[str, dict[str, Any]]:
        ordered = sorted(set(memory_ids))
        if not ordered:
            return {}
        placeholders = ",".join(["%s"] * len(ordered))
        suffix = " FOR UPDATE OF mr" if for_update else ""
        rows = conn.execute(
            f"""
            SELECT mr.id::text AS id, mr.user_id, mr.memory_type, mr.category,
                   mr.scope_type, mr.scope_key, mr.capture_mode, mr.normalized_key,
                   mr.cardinality, mr.canonical_hash, mr.display_text,
                   mr.confidence, mr.importance, mr.source_quality, mr.sensitivity,
                   mr.lifecycle_class, mr.valid_from, mr.valid_until,
                   mr.last_confirmed_at, mr.last_accessed_at, mr.access_count,
                   mr.status, mr.schema_version, mr.row_version,
                   mr.created_at, mr.updated_at,
                   COALESCE(sv.normalized_value, ee.event_payload, '{{}}'::jsonb) AS payload
            FROM memory_records mr
            LEFT JOIN memory_semantic_values sv ON sv.memory_id = mr.id
            LEFT JOIN memory_episodic_events ee ON ee.memory_id = mr.id
            WHERE mr.user_id=%s AND mr.id IN ({placeholders})
            ORDER BY mr.id
            {suffix}
            """,
            tuple([user_id, *ordered]),
        ).fetchall()
        return {str(row["id"]): dict(row) for row in rows}

    @staticmethod
    def _append_pg_event(
        conn,
        *,
        user_id: str,
        memory_id: str,
        action: str,
        reason: str,
        actor_id: str,
        before: dict[str, Any],
        after: dict[str, Any],
        row_version: int,
    ) -> dict[str, Any]:
        event = {
            "id": str(uuid.uuid4()), "owner_id": user_id, "memory_id": memory_id,
            "action": action, "reason": reason, "actor_id": actor_id,
            "before_snapshot": before, "after_snapshot": after,
            "row_version": row_version, "created_at": now_iso(),
        }
        conn.execute(
            """
            INSERT INTO memory_record_events
              (id,owner_id,memory_id,action,reason,actor_id,before_snapshot,after_snapshot,row_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
            """,
            (
                event["id"], user_id, memory_id, action, reason, actor_id,
                json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), row_version,
            ),
        )
        return event


__all__ = [
    "MemoryAction", "MemoryConflictError", "MemoryGovernance", "MemoryGovernanceError",
    "MemoryNotFoundError", "MemoryValidationError",
]
