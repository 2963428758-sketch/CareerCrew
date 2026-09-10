"""Owner-scoped conversation traceability for the Phase 8 workspace.

The conversation store remains the source of truth for messages.  This module
only stores the user-created links around those messages: bookmarks, bounded
branches, and action items.  Search deliberately returns a short snippet and a
transparent ``text_fallback`` mode until an embedding index is available; it
never turns a vector/search hit into authorization.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime
from typing import Any

from careercrew_core.conversation.store import ConversationStore, OwnershipError
from careercrew_core.conversation.uuid7 import uuid7


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _public(row: dict | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def _clean_text(value: Any, *, field: str, limit: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} 不能为空")
    if len(text) > limit:
        raise ValueError(f"{field} 不能超过 {limit} 个字符")
    return text


def _tags(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    if len(values) > 20:
        raise ValueError("标签不能超过 20 个")
    result: list[str] = []
    for value in values:
        tag = _clean_text(value, field="标签", limit=40, required=True)
        if tag not in result:
            result.append(tag)
    return result


def _snippet(content: Any, limit: int = 280) -> str:
    return re.sub(r"\s+", " ", str(content or "")).strip()[:limit]


class WorkspaceTraceability:
    """Conversation search and user-authored links around conversation data.

    ``FakeConversationDb`` is intentionally supported without a second fake
    database.  Production uses the shared psycopg pool and the 0012 tables.
    The service is attached to the runtime by the API router, so its fake
    state survives multiple requests in one test/runtime process.
    """

    def __init__(self, conversation_store: ConversationStore, *, pool=None) -> None:
        self.conversation_store = conversation_store
        self._db = conversation_store._db  # the store is the owner/auth boundary
        self._pool = pool
        if self._pool is None and hasattr(self._db, "_get_pool"):
            self._pool = self._db._get_pool()
        self._lock = threading.RLock()
        self._fake = self._pool is None
        self._bookmarks: dict[tuple[str, str], dict] = {}
        self._branches: dict[str, dict] = {}
        self._action_items: dict[str, dict] = {}

    # ── common ownership / connection helpers ──

    def _message(self, owner_id: str, message_id: str) -> dict:
        message = self.conversation_store.get_message(owner_id, message_id)
        if message is None:
            # Foreign and missing messages intentionally have the same error.
            raise PermissionError("消息不存在或不属于当前账号")
        return message

    def _owned_thread(self, owner_id: str, thread_id: str) -> dict:
        try:
            conversation = self.conversation_store.get_conversation(thread_id, owner_id)
        except OwnershipError as exc:
            raise PermissionError("会话不存在或不属于当前账号") from exc
        if conversation is None:
            raise PermissionError("会话不存在或不属于当前账号")
        return conversation

    def _connect(self):
        if self._pool is None:  # pragma: no cover - guarded by fake branch
            raise RuntimeError("workspace postgres pool is not configured")
        return self._pool.connection()

    @staticmethod
    def _row(row: Any) -> dict:
        return _public(dict(row))

    # ── search ──

    def search(self, query: str, owner_id: str, limit: int = 20) -> dict:
        text = _clean_text(query, field="搜索词", limit=200, required=True)
        if not 1 <= limit <= 50:
            raise ValueError("每页数量必须为 1–50")
        if self._fake:
            rows = [
                dict(row)
                for row in getattr(self._db, "_messages", {}).values()
                if row.get("user_id") == owner_id and not row.get("deleted_at")
                and text.casefold() in str(row.get("content") or "").casefold()
            ]
            rows.sort(
                key=lambda row: (
                    -str(row.get("content") or "").casefold().count(text.casefold()),
                    str(row.get("created_at") or ""),
                    str(row.get("id") or ""),
                ),
                reverse=False,
            )
            items = [self._search_item(row, score=1.0) for row in rows[:limit]]
            return {"mode": "text_fallback", "query": text, "items": items,
                    "total": len(rows)}

        pattern = f"%{text}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.id, m.thread_id, m.turn_id, m.role, m.content,
                       m.created_at, c.title AS thread_title,
                       CASE WHEN lower(m.content) LIKE lower(%s) THEN 1.0 ELSE 0.5 END AS score,
                       COUNT(*) OVER() AS total_count
                FROM messages m
                JOIN conversations c ON c.id = m.thread_id AND c.user_id = m.user_id
                WHERE m.user_id=%s AND m.deleted_at IS NULL
                  AND (m.content ILIKE %s OR to_tsvector('simple', m.content)
                       @@ plainto_tsquery('simple', %s))
                ORDER BY score DESC, m.created_at DESC, m.id DESC
                LIMIT %s
                """,
                (pattern, owner_id, pattern, text, limit),
            ).fetchall()
        items = [self._search_item(self._row(row), score=float(row["score"])) for row in rows]
        return {"mode": "text_fallback", "query": text, "items": items,
                "total": int(rows[0]["total_count"]) if rows else 0}

    def _search_item(self, row: dict, *, score: float) -> dict:
        return {
            "message_id": str(row["id"]),
            "thread_id": str(row["thread_id"]),
            "turn_id": str(row["turn_id"]),
            "role": row.get("role", ""),
            "snippet": _snippet(row.get("content")),
            "thread_title": row.get("thread_title"),
            "created_at": _public({"created_at": row.get("created_at")})["created_at"],
            "score": score,
        }

    # ── bookmarks ──

    def upsert_bookmark(self, owner_id: str, message_id: str, *, note: str = "",
                        tags: list[str] | None = None) -> dict:
        self._message(owner_id, message_id)
        clean_note = _clean_text(note, field="备注", limit=500)
        clean_tags = _tags(tags)
        now = _now()
        if self._fake:
            key = (owner_id, message_id)
            row = self._bookmarks.get(key) or {
                "id": str(uuid7()), "owner_id": owner_id, "message_id": message_id,
                "created_at": now,
            }
            row.update({"note": clean_note, "tags": clean_tags, "updated_at": now})
            self._bookmarks[key] = row
            return self._bookmark_public(row)
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                """
                INSERT INTO conversation_bookmarks
                    (id, owner_id, message_id, note, tags, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (owner_id, message_id) DO UPDATE SET
                    note=EXCLUDED.note, tags=EXCLUDED.tags, updated_at=EXCLUDED.updated_at
                RETURNING *
                """,
                (str(uuid7()), owner_id, message_id, clean_note,
                 json.dumps(clean_tags, ensure_ascii=False), now, now),
            ).fetchone()
        return self._bookmark_public(self._row(row))

    def list_bookmarks(self, owner_id: str) -> list[dict]:
        if self._fake:
            rows = [
                row for (user, _), row in self._bookmarks.items()
                if user == owner_id and self.conversation_store.get_message(owner_id, row["message_id"])
            ]
            rows.sort(key=lambda row: (str(row.get("updated_at") or ""), row["id"]), reverse=True)
            return [self._bookmark_public(row) for row in rows]
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT b.*, left(m.content, 280) AS snippet "
                "FROM conversation_bookmarks b JOIN messages m ON m.id=b.message_id "
                "WHERE b.owner_id=%s ORDER BY b.updated_at DESC, b.id DESC", (owner_id,)
            ).fetchall()
        return [self._bookmark_public(self._row(row)) for row in rows]

    def delete_bookmark(self, owner_id: str, message_id: str) -> bool:
        if self._fake:
            return self._bookmarks.pop((owner_id, message_id), None) is not None
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "DELETE FROM conversation_bookmarks WHERE owner_id=%s AND message_id=%s RETURNING id",
                (owner_id, message_id),
            ).fetchone()
        return row is not None

    def _bookmark_public(self, row: dict) -> dict:
        result = _public(row) or {}
        message = self.conversation_store.get_message(result["owner_id"], result["message_id"])
        result["snippet"] = _snippet(message.get("content")) if message else result.get("snippet", "")
        tags = result.get("tags")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = []
        result["tags"] = tags or []
        result.pop("owner_id", None)
        return result

    # ── source-linked action items ──

    def create_action_item(self, owner_id: str, message_id: str, *, title: str,
                           note: str = "", due_date: str | None = None) -> dict:
        self._message(owner_id, message_id)
        clean_title = _clean_text(title, field="行动项标题", limit=200, required=True)
        clean_note = _clean_text(note, field="行动项说明", limit=2000)
        due = _clean_text(due_date, field="截止日期", limit=10) if due_date else None
        if due:
            try:
                date.fromisoformat(due)
            except ValueError as exc:
                raise ValueError("截止日期格式应为 YYYY-MM-DD") from exc
        now = _now()
        item_id = str(uuid7())
        if self._fake:
            row = {
                "id": item_id, "owner_id": owner_id, "source_message_id": message_id,
                "title": clean_title, "note": clean_note, "due_date": due,
                "status": "open", "created_at": now, "updated_at": now,
            }
            self._action_items[item_id] = row
            return self._action_public(row)
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                """
                INSERT INTO workspace_action_items
                    (id, owner_id, source_message_id, title, note, due_date,
                     status, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,'open',%s,%s) RETURNING *
                """,
                (item_id, owner_id, message_id, clean_title, clean_note, due, now, now),
            ).fetchone()
        return self._action_public(self._row(row))

    def list_action_items(self, owner_id: str) -> list[dict]:
        if self._fake:
            rows = [
                row for row in self._action_items.values()
                if row["owner_id"] == owner_id
                and self.conversation_store.get_message(owner_id, row["source_message_id"])
            ]
            rows.sort(key=lambda row: (str(row.get("updated_at") or ""), row["id"]), reverse=True)
            return [self._action_public(row) for row in rows]
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT a.*, left(m.content, 280) AS source_snippet "
                "FROM workspace_action_items a JOIN messages m ON m.id=a.source_message_id "
                "WHERE a.owner_id=%s ORDER BY a.updated_at DESC, a.id DESC", (owner_id,)
            ).fetchall()
        return [self._action_public(self._row(row)) for row in rows]

    def update_action_item(self, owner_id: str, item_id: str, *, status: str) -> dict | None:
        if status not in {"open", "done", "dismissed"}:
            raise ValueError("行动项状态不正确")
        now = _now()
        if self._fake:
            row = self._action_items.get(item_id)
            if row is None or row["owner_id"] != owner_id:
                return None
            row.update({"status": status, "updated_at": now})
            return self._action_public(row)
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "UPDATE workspace_action_items SET status=%s, updated_at=%s "
                "WHERE owner_id=%s AND id=%s RETURNING *", (status, now, owner_id, item_id)
            ).fetchone()
        return self._action_public(self._row(row)) if row else None

    def _action_public(self, row: dict) -> dict:
        result = _public(row) or {}
        message = self.conversation_store.get_message(result["owner_id"], result["source_message_id"])
        result["source_snippet"] = _snippet(message.get("content")) if message else result.get("source_snippet", "")
        result.pop("owner_id", None)
        return result

    # ── bounded branches ──

    def create_branch(self, owner_id: str, source_thread_id: str,
                      cutoff_message_id: str, *, title: str | None = None) -> dict:
        source = self._owned_thread(owner_id, source_thread_id)
        cutoff = self._message(owner_id, cutoff_message_id)
        messages = self.conversation_store.list_messages(source_thread_id, owner_id)
        cutoff_index = next((i for i, row in enumerate(messages)
                             if row["id"] == cutoff["id"]), None)
        if cutoff_index is None or cutoff.get("thread_id") != source["id"]:
            raise PermissionError("截止消息不属于指定会话")
        bounded = messages[:cutoff_index + 1]
        branch_title = _clean_text(title, field="分支标题", limit=255) if title else ""
        branch_title = branch_title or f"{source.get('title') or '对话'} 分支"
        branch_thread_id = str(uuid7())
        self.conversation_store.ensure_conversation(
            branch_thread_id, owner_id, source.get("module") or "chat",
            title=branch_title, retrieval_scope=source.get("retrieval_scope"),
        )
        copied = 0
        current_turn: str | None = None
        for message in bounded:
            if message.get("turn_id") != current_turn:
                current_turn = message.get("turn_id")
                new_turn = self.conversation_store.next_turn(branch_thread_id, owner_id)
            if message.get("role") == "user":
                self.conversation_store.add_user_message(
                    new_turn["id"], branch_thread_id, owner_id,
                    message.get("content") or "", message.get("status") or "completed",
                    metadata=message.get("metadata"),
                )
            elif message.get("role") == "assistant":
                cloned = self.conversation_store.add_assistant_message(
                    new_turn["id"], branch_thread_id, owner_id, "", None, None,
                )
                self.conversation_store.set_message_content(
                    owner_id, cloned["id"], message.get("content") or "",
                    status=message.get("status") or "completed",
                    metadata=message.get("metadata"),
                )
            else:
                continue
            copied += 1
        row = {
            "id": str(uuid7()), "owner_id": owner_id,
            "source_thread_id": source["id"], "cutoff_message_id": cutoff["id"],
            "branch_thread_id": branch_thread_id, "title": branch_title,
            "message_count": copied, "created_at": _now(),
        }
        if self._fake:
            self._branches[row["id"]] = row
        else:
            with self._connect() as conn, conn.transaction():
                inserted = conn.execute(
                    """
                    INSERT INTO conversation_branches
                        (id, owner_id, source_thread_id, cutoff_message_id,
                         branch_thread_id, title, message_count, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
                    """,
                    (row["id"], owner_id, row["source_thread_id"], row["cutoff_message_id"],
                     row["branch_thread_id"], row["title"], copied, row["created_at"]),
                ).fetchone()
                row = self._row(inserted)
        row.pop("owner_id", None)
        return row

    def list_branches(self, owner_id: str) -> list[dict]:
        if self._fake:
            rows = [row for row in self._branches.values() if row["owner_id"] == owner_id]
            rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        else:
            with self._connect() as conn:
                rows = [self._row(row) for row in conn.execute(
                    "SELECT * FROM conversation_branches WHERE owner_id=%s "
                    "ORDER BY created_at DESC, id DESC", (owner_id,)
                ).fetchall()]
        return [{key: value for key, value in row.items() if key != "owner_id"} for row in rows]
