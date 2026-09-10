"""Owner-scoped semantic search for ordinary conversation messages.

Conversation rows remain the source of truth.  This module only maintains a
rebuildable Qdrant projection and maps hits back to current source rows before
returning them.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from careercrew_ai.embedding.base_embedding import BaseEmbedding
from careercrew_ai.vector_store.base_vector_store import (
    BaseVectorStore,
    QueryResult,
    VectorRecord,
)

CONVERSATION_RECORD_TYPE = "conversation_message"


def _clean_query(value: Any) -> str:
    query = str(value or "").strip()
    if not query:
        raise ValueError("搜索词 不能为空")
    if len(query) > 200:
        raise ValueError("搜索词 不能超过 200 个字符")
    return query


def _active_rows(owner_id: str, rows: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in rows:
        if str(row.get("user_id") or "") != owner_id:
            continue
        message_id = str(row.get("id") or "")
        content = str(row.get("content") or "")
        if not message_id or not content.strip() or row.get("deleted_at"):
            continue
        result[message_id] = dict(row)
    return result


def _message_metadata(owner_id: str, row: dict) -> dict[str, str]:
    return {
        "record_type": CONVERSATION_RECORD_TYPE,
        "message_id": str(row["id"]),
        "owner_user_id": owner_id,
        "user_id": owner_id,
        "thread_id": str(row.get("thread_id") or ""),
        "role": str(row.get("role") or ""),
        "status": str(row.get("status") or ""),
    }


def _signature(row: dict) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("id") or ""),
        str(row.get("content") or ""),
        str(row.get("role") or ""),
        str(row.get("status") or ""),
        str(row.get("deleted_at") or ""),
    )


def _created_at(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _item(row: dict, score: float) -> dict:
    return {
        "message_id": str(row["id"]),
        "thread_id": str(row["thread_id"]),
        "turn_id": str(row["turn_id"]),
        "role": row.get("role", ""),
        "snippet": " ".join(str(row.get("content") or "").split())[:280],
        "thread_title": row.get("thread_title"),
        "created_at": _created_at(row.get("created_at")),
        "score": score,
    }


class ConversationSemanticSearch:
    """Incremental embedding projection and owner-scoped message retrieval."""

    def __init__(
        self,
        embedding: BaseEmbedding,
        vector_store: BaseVectorStore,
        message_loader: Callable[[str], list[dict]],
    ) -> None:
        self._embedding = embedding
        self._vector_store = vector_store
        self._message_loader = message_loader
        self._lock = threading.RLock()
        self._known_ids: dict[str, set[str]] = {}

    @staticmethod
    def _filters(owner_id: str) -> dict[str, str]:
        return {
            "record_type": CONVERSATION_RECORD_TYPE,
            "owner_user_id": owner_id,
        }

    def sync(self, owner_id: str, rows: list[dict]) -> None:
        """Synchronize one owner's active messages into the vector projection."""
        owner = str(owner_id)
        current = _active_rows(owner, rows)
        current_ids = set(current)
        with self._lock:
            existing = self._vector_store.get_by_ids(
                list(current_ids), filters=self._filters(owner),
            ) if current_ids else []
            existing_by_id = {str(record.id): record for record in existing}
            changed = []
            for message_id, row in current.items():
                record = existing_by_id.get(message_id)
                expected_metadata = _message_metadata(owner, row)
                if (
                    record is None
                    or record.text != str(row.get("content") or "")
                    or any(record.metadata.get(key) != value
                           for key, value in expected_metadata.items())
                ):
                    changed.append((row, expected_metadata))

            if changed:
                output = self._embedding.encode(
                    [str(row.get("content") or "") for row, _ in changed]
                )
                dense = getattr(output, "dense", None)
                if dense is None or len(dense) != len(changed):
                    raise RuntimeError("embedding 返回的 dense 数量不匹配")
                sparse = getattr(output, "sparse", None)
                records = []
                for index, (row, metadata) in enumerate(changed):
                    records.append(VectorRecord(
                        id=str(row["id"]),
                        dense=dense[index],
                        sparse=sparse[index] if sparse is not None else None,
                        text=str(row.get("content") or ""),
                        metadata=metadata,
                    ))
                self._vector_store.upsert(records)

            # The process-local set catches deletions without requiring a
            # collection-wide scan.  Unknown stale points are still harmless:
            # search maps every hit back to the current source rows.
            stale_ids = self._known_ids.get(owner, set()) - current_ids
            for message_id in stale_ids:
                self._vector_store.delete_by_metadata({
                    **self._filters(owner), "message_id": message_id,
                })
            self._known_ids[owner] = current_ids

    def search(self, query: str, owner_id: str, limit: int = 20) -> dict:
        text = _clean_query(query)
        if not 1 <= limit <= 50:
            raise ValueError("每页数量必须为 1–50")
        owner = str(owner_id)
        rows = self._message_loader(owner)
        current = _active_rows(owner, rows)
        self.sync(owner, rows)
        if not current:
            return {"mode": "embedding", "query": text, "items": [], "total": 0}

        output = self._embedding.encode([text])
        dense = getattr(output, "dense", None)
        if dense is None or len(dense) != 1:
            raise RuntimeError("embedding 返回的查询向量数量不匹配")
        sparse = getattr(output, "sparse", None)
        hits: list[QueryResult] = self._vector_store.query(
            dense[0],
            top_k=min(200, max(limit * 4, 20)),
            filters=self._filters(owner),
            sparse=sparse[0] if sparse is not None else None,
        )
        items = []
        seen: set[str] = set()
        for hit in hits:
            message_id = str(hit.metadata.get("message_id") or hit.id)
            row = current.get(message_id)
            if row is None or message_id in seen:
                continue
            # Defense in depth in case a custom vector backend ignores filters.
            if str(hit.metadata.get("owner_user_id") or "") != owner:
                continue
            seen.add(message_id)
            items.append(_item(row, float(hit.score)))
            if len(items) >= limit:
                break
        return {
            "mode": "embedding",
            "query": text,
            "items": items,
            "total": len(items),
        }
