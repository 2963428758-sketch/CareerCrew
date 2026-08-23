"""长期记忆向量 outbox worker 与纯函数对账。"""
from __future__ import annotations

from typing import Any


def reconcile_vector_ids(active_memory_ids: set[str], indexed_memory_ids: set[str]) -> dict[str, list[str]]:
    """返回需要补建和需要清理的集合，调用方决定何时执行外部写操作。"""
    return {
        "missing": sorted(active_memory_ids - indexed_memory_ids),
        "orphaned": sorted(indexed_memory_ids - active_memory_ids),
    }


def drain_vector_outbox(repository, indexer: Any, *, limit: int = 50) -> dict[str, int]:
    """执行一批任务。indexer 提供 upsert_memory(record) / delete_memory(id)。"""
    processed = failed = 0
    for task in repository.claim_vector_outbox(limit=limit):
        try:
            if task["operation"] == "delete":
                indexer.delete_memory(task["memory_id"])
            else:
                record = repository.get(task["memory_id"])
                if record is not None and record.get("status") == "active":
                    indexer.upsert_memory(record)
            repository.complete_vector_outbox(task["id"])
            processed += 1
        except Exception as exc:  # worker 失败只能重试，不能影响数据库真相
            repository.fail_vector_outbox(task["id"], f"{type(exc).__name__}: {exc}")
            failed += 1
    return {"processed": processed, "failed": failed}


class MemoryRecordVectorIndexer:
    """把 active memory_records 编码到现有 episodic-memory collection。"""

    def __init__(self, embedding, store) -> None:
        self._embedding = embedding
        self._store = store

    def upsert_memory(self, record: dict[str, Any]) -> None:
        from careercrew_ai.vector_store.base_vector_store import VectorRecord

        text = str(record.get("display_text") or "")
        output = self._embedding.encode([text])
        self._store.upsert([VectorRecord(
            id=str(record["id"]), dense=output.dense[0],
            sparse=output.sparse[0] if output.sparse else None, text=text,
            metadata={
                "memory_id": str(record["id"]), "user_id": str(record["user_id"]),
                "type": str(record["memory_type"]), "category": str(record["category"]),
            },
        )])

    def delete_memory(self, memory_id: str) -> None:
        # 物理点 ID 与 Qdrant 的租户命名空间映射有关，按稳定 payload 删除最安全。
        self._store.delete_by_metadata({"memory_id": memory_id})
