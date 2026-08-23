"""可演进长期记忆记录仓储。

这层只依赖 ``MemoryDb`` 已有的稳定读接口，因此既可用于生产回填，也可在
FakeMemoryDb 单测中运行。新表的实际写入由 ``LongTermMemoryRepository`` 负责，
避免把迁移逻辑散落在路由或 Agent 工具中。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable


TRANSCRIPT_TYPES = frozenset({"user_message", "agent_response"})


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BackfillItem:
    """一条可审计的旧数据回填候选；不会包含聊天 transcript。"""

    user_id: str
    memory_type: str
    category: str
    normalized_key: str
    display_text: str
    payload: dict[str, Any]
    source_type: str
    legacy_id: str
    occurred_at: str | None = None


@dataclass
class BackfillReport:
    scanned_facts: int = 0
    scanned_events: int = 0
    skipped_transcripts: int = 0
    skipped_invalid: int = 0
    candidates: list[BackfillItem] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "scanned_facts": self.scanned_facts,
            "scanned_events": self.scanned_events,
            "skipped_transcripts": self.skipped_transcripts,
            "skipped_invalid": self.skipped_invalid,
            "candidates": len(self.candidates),
        }


def build_legacy_backfill(db, user_ids: Iterable[str]) -> BackfillReport:
    """从兼容表构建回填候选，纯读取、可重复执行。"""
    report = BackfillReport()
    for user_id in user_ids:
        for fact in db.list_facts(user_id):
            report.scanned_facts += 1
            name = str(fact.get("name") or "").strip()
            if not name:
                report.skipped_invalid += 1
                continue
            content = fact.get("content") or {}
            report.candidates.append(BackfillItem(
                user_id=user_id,
                memory_type="semantic",
                category=str(fact.get("type") or "profile"),
                normalized_key=f"semantic:{name.casefold()}",
                display_text=str(fact.get("description") or name),
                payload={"value": content, "legacy_name": name},
                source_type="legacy_semantic_fact",
                legacy_id=name,
                occurred_at=str(fact.get("modified_at") or "") or None,
            ))
        for event in db.list_episodic(user_id):
            report.scanned_events += 1
            event_type = str(event.get("type") or "").strip()
            if event_type in TRANSCRIPT_TYPES:
                report.skipped_transcripts += 1
                continue
            entry_id = str(event.get("id") or "").strip()
            if not event_type or not entry_id:
                report.skipped_invalid += 1
                continue
            content = event.get("content")
            report.candidates.append(BackfillItem(
                user_id=user_id,
                memory_type="episodic",
                category=event_type,
                normalized_key=f"event:{event_type}:{canonical_hash(content)}",
                display_text=f"{event_type}: {json.dumps(content, ensure_ascii=False, sort_keys=True)}",
                payload={"value": content, "thread_id": event.get("thread_id")},
                source_type="legacy_episodic_event",
                legacy_id=entry_id,
                occurred_at=str(event.get("ts") or "") or None,
            ))
    return report


class LongTermMemoryRepository:
    """面向新 ``memory_records`` 模型的最小、可审计仓储。

    FakeMemoryDb 使用进程内字典；PostgresMemoryDb 通过其连接池执行迁移定义的
    SQL。任何未迁移生产库会得到清晰错误，而不会悄悄退回旧表继续制造双写。
    """

    def __init__(self, db) -> None:
        self._db = db

    @property
    def _fake(self) -> bool:
        return self._db.__class__.__name__ == "FakeMemoryDb"

    def _fake_state(self) -> dict[str, Any]:
        if not hasattr(self._db, "_long_term_memory"):
            self._db._long_term_memory = {
                "records": {}, "sources": {}, "relations": {}, "outbox": {}, "traces": {},
            }
        return self._db._long_term_memory

    def _pg(self, callback):
        # PostgresMemoryDb 已以 RLock + pool 管理事务；此处仅作为新表 repository 的
        # 受控扩展入口，避免泄漏连接到上层 service。
        with self._db.write_lock, self._db._borrow() as conn:
            return callback(conn)

    def upsert(self, item: BackfillItem, *, capture_mode: str = "migration",
               importance: float = 0.5, confidence: float = 1.0) -> tuple[dict[str, Any], bool]:
        """写入当前值；同值合并来源，异值 supersede 旧值。"""
        if self._fake:
            state = self._fake_state()
            for record in state["records"].values():
                if (record["user_id"], record["normalized_key"], record["status"]) == (
                    item.user_id, item.normalized_key, "active",
                ):
                    if record["canonical_hash"] == canonical_hash(item.payload.get("value")):
                        record["last_confirmed_at"] = item.occurred_at or now_iso()
                        record["updated_at"] = now_iso()
                        self.add_source(record["id"], item.source_type, {"legacy_id": item.legacy_id})
                        return dict(record), False
                    record["status"] = "superseded"
                    record["updated_at"] = now_iso()
                    old_id = record["id"]
                    break
            else:
                old_id = None
            record = self._new_record(item, capture_mode, importance, confidence)
            state["records"][record["id"]] = record
            self.add_source(record["id"], item.source_type, {"legacy_id": item.legacy_id})
            if old_id:
                self.add_relation(record["id"], old_id, "supersedes")
            self.enqueue_vector(record["id"], item.user_id, "upsert")
            return dict(record), True

        def _write(conn):
            row = conn.execute(
                "SELECT id, user_id, memory_type, category, normalized_key, canonical_hash, display_text, status, "
                "row_version, created_at, updated_at FROM memory_records "
                "WHERE user_id=%s AND normalized_key=%s AND status='active' LIMIT 1",
                (item.user_id, item.normalized_key),
            ).fetchone()
            if row:
                current = dict(row)
                if current["canonical_hash"] == canonical_hash(item.payload.get("value")):
                    conn.execute(
                        "UPDATE memory_records SET last_confirmed_at=%s,updated_at=now(),row_version=row_version+1 WHERE id=%s",
                        (item.occurred_at or now_iso(), current["id"]),
                    )
                    self._add_source_pg(conn, current["id"], item.source_type, {"legacy_id": item.legacy_id})
                    return current, False
                conn.execute(
                    "UPDATE memory_records SET status='superseded',updated_at=now(),row_version=row_version+1 WHERE id=%s",
                    (current["id"],),
                )
            record = self._new_record(item, capture_mode, importance, confidence)
            conn.execute(
                "INSERT INTO memory_records (id,user_id,memory_type,category,capture_mode,normalized_key,"
                "canonical_hash,display_text,confidence,importance,status,valid_from,last_confirmed_at,"
                "created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s)",
                (record["id"], record["user_id"], record["memory_type"], record["category"],
                 record["capture_mode"], record["normalized_key"], record["canonical_hash"],
                 record["display_text"], record["confidence"], record["importance"],
                 record["valid_from"], record["last_confirmed_at"], record["created_at"], record["updated_at"]),
            )
            if item.memory_type == "semantic":
                conn.execute(
                    "INSERT INTO memory_semantic_values (memory_id,normalized_value,value_hash) VALUES (%s,%s::jsonb,%s)",
                    (record["id"], json.dumps(item.payload.get("value"), ensure_ascii=False), record["canonical_hash"]),
                )
            else:
                conn.execute(
                    "INSERT INTO memory_episodic_events (memory_id,event_type,occurred_at,event_payload) "
                    "VALUES (%s,%s,%s,%s::jsonb)",
                    (record["id"], item.category, item.occurred_at or record["created_at"],
                     json.dumps(item.payload.get("value"), ensure_ascii=False)),
                )
            self._add_source_pg(conn, record["id"], item.source_type, {"legacy_id": item.legacy_id})
            if row:
                self._add_relation_pg(conn, record["id"], dict(row)["id"], "supersedes")
            self._enqueue_vector_pg(conn, record["id"], item.user_id, "upsert")
            return record, True
        return self._pg(_write)

    def _new_record(self, item: BackfillItem, capture_mode: str, importance: float,
                    confidence: float) -> dict[str, Any]:
        ts = item.occurred_at or now_iso()
        return {
            "id": str(uuid.uuid4()), "user_id": item.user_id, "memory_type": item.memory_type,
            "category": item.category, "capture_mode": capture_mode,
            "normalized_key": item.normalized_key, "canonical_hash": canonical_hash(item.payload.get("value")),
            "display_text": item.display_text, "confidence": confidence, "importance": importance,
            "status": "active", "row_version": 1, "valid_from": ts, "last_confirmed_at": ts,
            "created_at": ts, "updated_at": ts, "payload": item.payload,
        }

    def add_source(self, memory_id: str, source_type: str, metadata: dict[str, Any]) -> None:
        if self._fake:
            state = self._fake_state()
            state["sources"].setdefault(memory_id, []).append({
                "id": str(uuid.uuid4()), "source_type": source_type, "metadata": dict(metadata),
                "observed_at": now_iso(),
            })
            return
        self._pg(lambda conn: self._add_source_pg(conn, memory_id, source_type, metadata))

    def add_relation(self, from_memory_id: str, to_memory_id: str, relation_type: str) -> None:
        if self._fake:
            state = self._fake_state()
            state["relations"][str(uuid.uuid4())] = {
                "from_memory_id": from_memory_id, "to_memory_id": to_memory_id,
                "relation_type": relation_type, "created_at": now_iso(),
            }
            return
        self._pg(lambda conn: self._add_relation_pg(conn, from_memory_id, to_memory_id, relation_type))

    def list_sources(self, memory_id: str) -> list[dict[str, Any]]:
        if self._fake:
            return [dict(row) for row in self._fake_state()["sources"].get(memory_id, [])]
        return self._pg(lambda conn: [dict(row) for row in conn.execute(
            "SELECT id,source_type,source_excerpt_redacted,asserted_by,evidence_strength,observed_at "
            "FROM memory_sources WHERE memory_id=%s ORDER BY observed_at", (memory_id,),
        ).fetchall()])

    def list_relations(self, memory_id: str) -> list[dict[str, Any]]:
        if self._fake:
            return [dict(row) for row in self._fake_state()["relations"].values()
                    if row["from_memory_id"] == memory_id or row["to_memory_id"] == memory_id]
        return self._pg(lambda conn: [dict(row) for row in conn.execute(
            "SELECT from_memory_id,to_memory_id,relation_type,confidence,metadata,created_at "
            "FROM memory_relations WHERE from_memory_id=%s OR to_memory_id=%s ORDER BY created_at",
            (memory_id, memory_id),
        ).fetchall()])

    @staticmethod
    def _add_source_pg(conn, memory_id: str, source_type: str, metadata: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO memory_sources (id,memory_id,source_type,source_excerpt_redacted,asserted_by) "
            "VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), memory_id, source_type,
             json.dumps(metadata, ensure_ascii=False, sort_keys=True), "migration"),
        )

    @staticmethod
    def _add_relation_pg(conn, from_memory_id: str, to_memory_id: str, relation_type: str) -> None:
        conn.execute(
            "INSERT INTO memory_relations (id,from_memory_id,to_memory_id,relation_type) VALUES (%s,%s,%s,%s)",
            (str(uuid.uuid4()), from_memory_id, to_memory_id, relation_type),
        )

    def list_active(self, user_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        if self._fake:
            records = [dict(x) for x in self._fake_state()["records"].values()
                       if x["user_id"] == user_id and x["status"] == "active"]
            return sorted(records, key=lambda x: (x["updated_at"], x["id"]), reverse=True)[:limit]
        return self._pg(lambda conn: [dict(row) for row in conn.execute(
            "SELECT id,user_id,memory_type,category,normalized_key,display_text,confidence,importance,"
            "status,row_version,created_at,updated_at FROM memory_records "
            "WHERE user_id=%s AND status='active' ORDER BY updated_at DESC,id DESC LIMIT %s",
            (user_id, limit),
        ).fetchall()])

    def enqueue_vector(self, memory_id: str, user_id: str, operation: str) -> None:
        if self._fake:
            self._fake_state()["outbox"][str(uuid.uuid4())] = {
                "id": str(uuid.uuid4()), "memory_id": memory_id, "user_id": user_id,
                "operation": operation, "attempts": 0, "processed_at": None, "available_at": now_iso(),
            }
            return
        self._pg(lambda conn: self._enqueue_vector_pg(conn, memory_id, user_id, operation))

    @staticmethod
    def _enqueue_vector_pg(conn, memory_id: str, user_id: str, operation: str) -> None:
        conn.execute(
            "INSERT INTO memory_vector_outbox (id,memory_id,user_id,operation,payload) VALUES (%s,%s,%s,%s,'{}'::jsonb)",
            (str(uuid.uuid4()), memory_id, user_id, operation),
        )

    def apply_backfill(self, report: BackfillReport) -> dict[str, int]:
        created = existing = 0
        for item in report.candidates:
            _record, did_create = self.upsert(item)
            created += int(did_create)
            existing += int(not did_create)
        return {"created": created, "existing": existing, **report.summary()}
