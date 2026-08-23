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
