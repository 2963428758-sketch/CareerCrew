"""Dry-run, safe and idempotent legacy-u_001 tenant migration."""
from __future__ import annotations

import json
import sqlite3

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from careercrew_ai.vector_store.qdrant_store import QdrantStore
from careercrew_core.state.checkpointer import tenant_thread_id
from scripts import migrate_legacy_tenant
from scripts.migrate_legacy_tenant import (
    first_admin_id,
    migrate_checkpoint_sqlite,
    migrate_local_resume_assets,
    migrate_qdrant_client,
)


def test_first_admin_is_migration_target(tmp_path) -> None:
    db = tmp_path / "accounts.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE accounts (id TEXT PRIMARY KEY, username TEXT, password_hash TEXT, role TEXT, created_at TEXT)"
        )
        conn.execute("INSERT INTO accounts VALUES ('u_user', 'user', 'x', 'user', '2026-01-01')")
        conn.execute("INSERT INTO accounts VALUES ('u_admin', 'admin', 'x', 'admin', '2026-01-02')")
    assert first_admin_id(db) == "u_admin"


def test_checkpoint_migration_is_dry_run_then_idempotent(tmp_path) -> None:
    db = tmp_path / "checkpoint.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT, "
            "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))"
        )
        conn.execute("INSERT INTO checkpoints VALUES ('shared', '', 'cp1')")

    dry = migrate_checkpoint_sqlite(db, "u_admin", apply=False)
    assert dry.changed == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT thread_id FROM checkpoints").fetchone()[0] == "shared"

    applied = migrate_checkpoint_sqlite(db, "u_admin", apply=True)
    assert applied.changed == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT thread_id FROM checkpoints").fetchone()[0] == tenant_thread_id(
            "u_admin", "shared"
        )
    assert migrate_checkpoint_sqlite(db, "u_admin", apply=True).changed == 0


def test_checkpoint_migration_handles_tenant_prefixed_public_id_and_wal_backups(
    tmp_path,
) -> None:
    db = tmp_path / "checkpoint.db"
    public_id = "tenant:7:u_adminpublic"
    writer = sqlite3.connect(db)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute(
            "CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT, "
            "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))"
        )
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute(
            "INSERT INTO checkpoints VALUES (?, '', 'cp1')",
            (public_id,),
        )
        writer.commit()

        dry = migrate_checkpoint_sqlite(db, "u_admin", apply=False)
        assert dry.changed == 1
        assert list(tmp_path.glob("checkpoint.db.pre-tenant-migration-*.bak")) == []
        assert writer.execute("SELECT thread_id FROM checkpoints").fetchone()[0] == public_id

        applied = migrate_checkpoint_sqlite(db, "u_admin", apply=True)
        assert applied.changed == 1
        assert writer.execute("SELECT thread_id FROM checkpoints").fetchone()[0] == tenant_thread_id(
            "u_admin", public_id,
        )
        backups = list(tmp_path.glob("checkpoint.db.pre-tenant-migration-*.bak"))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute("SELECT thread_id FROM checkpoints").fetchone()[0] == public_id

        assert migrate_checkpoint_sqlite(db, "u_admin", apply=True).changed == 0
        assert list(tmp_path.glob("checkpoint.db.pre-tenant-migration-*.bak")) == backups

        writer.execute("INSERT INTO checkpoints VALUES ('later-public', '', 'cp2')")
        writer.commit()
        assert migrate_checkpoint_sqlite(db, "u_admin", apply=True).changed == 1
        assert len(list(tmp_path.glob("checkpoint.db.pre-tenant-migration-*.bak"))) == 2
    finally:
        writer.close()


def test_resume_asset_migration_copies_thread_and_backs_up_metadata(tmp_path) -> None:
    data = tmp_path / "data"
    thread_dir = data / "uploads" / "resume_threads"
    library_dir = data / "uploads" / "resumes"
    thread_dir.mkdir(parents=True)
    library_dir.mkdir(parents=True)
    (thread_dir / "legacy-thread.txt").write_text("legacy resume", encoding="utf-8")
    meta = library_dir / "r1.json"
    meta.write_text(json.dumps({"resume_id": "r1"}), encoding="utf-8")

    dry = migrate_local_resume_assets(data, "u_admin", apply=False)
    assert dry.changed == 2
    assert "user_id" not in json.loads(meta.read_text(encoding="utf-8"))

    applied = migrate_local_resume_assets(data, "u_admin", apply=True)
    assert applied.changed == 2
    assert json.loads(meta.read_text(encoding="utf-8"))["user_id"] == "u_admin"
    assert (library_dir / "r1.json.pre-tenant-migration.bak").is_file()
    copied = list((thread_dir / "u_admin").glob("*.txt"))
    assert len(copied) == 1 and copied[0].read_text(encoding="utf-8") == "legacy resume"
    assert (thread_dir / "legacy-thread.txt").is_file()  # source is deliberately preserved
    assert migrate_local_resume_assets(data, "u_admin", apply=True).changed == 0


def test_qdrant_migration_rekeys_legacy_point_without_changing_logical_id() -> None:
    client = QdrantClient(":memory:")
    client.create_collection(
        "legacy", vectors_config={"text_dense": VectorParams(size=2, distance=Distance.COSINE)},
    )
    old_id = QdrantStore._to_qid("e_001")
    client.upsert(
        "legacy",
        [PointStruct(
            id=old_id, vector={"text_dense": [1.0, 0.0]},
            payload={"_id": "e_001", "text": "private legacy"},
        )],
    )

    assert migrate_qdrant_client(client, ["legacy"], "u_admin", apply=False).changed == 1
    applied = migrate_qdrant_client(client, ["legacy"], "u_admin", apply=True)
    assert applied.changed == 1
    points, _ = client.scroll("legacy", with_payload=True, with_vectors=False)
    assert len(points) == 1
    assert str(points[0].id) == QdrantStore._to_qid("e_001", "u_admin")
    assert points[0].payload["_id"] == "e_001"
    assert points[0].payload["user_id"] == "u_admin"
    assert migrate_qdrant_client(client, ["legacy"], "u_admin", apply=True).changed == 0


def _qdrant_migration_client() -> QdrantClient:
    client = QdrantClient(":memory:")
    client.create_collection(
        "legacy", vectors_config={"text_dense": VectorParams(size=2, distance=Distance.COSINE)},
    )
    return client


def _seed_interrupted_qdrant_copy(client: QdrantClient, *, destination_text: str) -> tuple[str, str]:
    logical_id = "e_retry"
    old_id = QdrantStore._to_qid(logical_id)
    expected_id = QdrantStore._to_qid(logical_id, "u_admin")
    client.upsert(
        "legacy",
        [
            PointStruct(
                id=old_id,
                vector={"text_dense": [1.0, 0.0]},
                payload={"_id": logical_id, "text": "private legacy"},
            ),
            PointStruct(
                id=expected_id,
                vector={"text_dense": [1.0, 0.0]},
                payload={
                    "_id": logical_id,
                    "text": destination_text,
                    "user_id": "u_admin",
                },
            ),
        ],
    )
    return old_id, expected_id


def test_qdrant_migration_retry_cleans_identical_destination_without_recopying() -> None:
    client = _qdrant_migration_client()
    old_id, expected_id = _seed_interrupted_qdrant_copy(
        client, destination_text="private legacy",
    )

    dry = migrate_qdrant_client(client, ["legacy"], "u_admin", apply=False)
    assert dry.changed == 1
    assert len(client.retrieve("legacy", ids=[old_id, expected_id])) == 2

    applied = migrate_qdrant_client(client, ["legacy"], "u_admin", apply=True)
    assert applied.changed == 1
    assert client.retrieve("legacy", ids=[old_id]) == []
    destination = client.retrieve("legacy", ids=[expected_id], with_payload=True)
    assert destination[0].payload["text"] == "private legacy"
    assert migrate_qdrant_client(client, ["legacy"], "u_admin", apply=True).changed == 0


def test_qdrant_migration_rejects_semantically_different_destination() -> None:
    client = _qdrant_migration_client()
    old_id, expected_id = _seed_interrupted_qdrant_copy(
        client, destination_text="different record",
    )

    result = migrate_qdrant_client(client, ["legacy"], "u_admin", apply=True)

    assert result.conflicts == 1
    assert len(client.retrieve("legacy", ids=[old_id, expected_id])) == 2


class _DeleteFailureClient:
    def __init__(self, wrapped: QdrantClient) -> None:
        self._wrapped = wrapped

    def __getattr__(self, name):
        return getattr(self._wrapped, name)

    def delete(self, *args, **kwargs):
        raise RuntimeError("injected delete interruption")


def test_qdrant_copy_then_delete_interruption_raises_and_retry_finishes() -> None:
    client = _qdrant_migration_client()
    logical_id = "e_interrupted"
    old_id = QdrantStore._to_qid(logical_id)
    expected_id = QdrantStore._to_qid(logical_id, "u_admin")
    client.upsert(
        "legacy",
        [PointStruct(
            id=old_id,
            vector={"text_dense": [1.0, 0.0]},
            payload={"_id": logical_id, "text": "private legacy"},
        )],
    )

    with pytest.raises(RuntimeError, match="injected delete interruption"):
        migrate_qdrant_client(_DeleteFailureClient(client), ["legacy"], "u_admin", apply=True)
    assert len(client.retrieve("legacy", ids=[old_id, expected_id])) == 2

    retry = migrate_qdrant_client(client, ["legacy"], "u_admin", apply=True)
    assert retry.changed == 1
    assert client.retrieve("legacy", ids=[old_id]) == []
    assert len(client.retrieve("legacy", ids=[expected_id])) == 1


def test_qdrant_cli_error_is_nonzero(tmp_path, monkeypatch) -> None:
    def fail_qdrant_settings():
        raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(migrate_legacy_tenant, "_qdrant_from_settings", fail_qdrant_settings)

    exit_code = migrate_legacy_tenant.main([
        "--target-user", "u_admin",
        "--checkpoint-db", str(tmp_path / "missing-checkpoint.db"),
        "--data-dir", str(tmp_path / "missing-data"),
    ])

    assert exit_code != 0
