"""knowledge 集合 payload 迁移：user_id → owner_user_id + visibility=private，物理 ID 不变。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from migrate_knowledge_visibility import migrate_collection  # noqa: E402
from careercrew_ai.vector_store.qdrant_store import QdrantStore
from careercrew_ai.vector_store.base_vector_store import VectorRecord


def _seed_store(valid_config_data):
    from qdrant_client import QdrantClient

    store = QdrantStore.__new__(QdrantStore)
    store._client = QdrantClient(":memory:")
    store._collection = "careercrew_mm"
    store._dim = 1024
    store._ensure_collection()
    store.upsert([VectorRecord(
        id="doc-p0", dense=[0.1] * 1024,
        metadata={"doc": "doc", "source": "doc.pdf", "category": "knowledge", "user_id": "u_001"},
    )])
    return store


def test_migration_moves_user_id_to_owner_and_is_idempotent(valid_config_data):
    store = _seed_store(valid_config_data)
    before = [p.id for p in store._client.scroll("careercrew_mm", limit=100, with_payload=False)[0]]

    changed, skipped, conflicts = migrate_collection(
        store._client, "careercrew_mm", "u_001", apply=False
    )
    assert changed == 1 and skipped == 0 and conflicts == 0
    assert store.count(filters={"owner_user_id": "u_001"}) == 0  # dry-run 未写

    changed, skipped, conflicts = migrate_collection(
        store._client, "careercrew_mm", "u_001", apply=True
    )
    assert changed == 1 and conflicts == 0
    assert store.count(filters={"owner_user_id": "u_001", "visibility": "private"}) == 1
    assert store.count(filters={"user_id": "u_001"}) == 0  # 旧键已删除

    after = [p.id for p in store._client.scroll("careercrew_mm", limit=100, with_payload=False)[0]]
    assert after == before  # 物理 ID 不变

    changed, skipped, conflicts = migrate_collection(
        store._client, "careercrew_mm", "u_001", apply=True
    )
    assert changed == 0 and skipped == 1 and conflicts == 0  # 幂等
