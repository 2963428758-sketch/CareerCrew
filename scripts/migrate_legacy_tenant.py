"""Attribute legacy single-user data to the first administrator tenant.

The command is a dry-run by default.  ``--apply`` is required for writes; it
never runs from application startup.  Local SQLite/files are backed up or
copied before mutation, Qdrant points are copied to their tenant-aware physical
id before the legacy point is removed, and Postgres updates (when an explicit
DSN is supplied) run in one transaction.  Existing destination conflicts are
reported and left untouched.  Re-running after success produces zero changes.

Examples::

    python scripts/migrate_legacy_tenant.py
    python scripts/migrate_legacy_tenant.py --apply
    python scripts/migrate_legacy_tenant.py --apply --postgres-dsn "$DATABASE_URL"
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from typing import Iterable
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_USER_ID = "u_001"
_CHECKPOINT_MIGRATION_TABLE = "careercrew_tenant_thread_migrations"


@dataclass
class MigrationResult:
    changed: int = 0
    conflicts: int = 0
    messages: list[str] = field(default_factory=list)

    def extend(self, other: "MigrationResult") -> None:
        self.changed += other.changed
        self.conflicts += other.conflicts
        self.messages.extend(other.messages)


def first_admin_id(account_db: str | Path) -> str:
    """Return the earliest administrator; fail instead of guessing a tenant."""
    path = Path(account_db)
    if not path.is_file():
        raise RuntimeError(f"account database does not exist: {path}")
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT id FROM accounts WHERE role='admin' ORDER BY created_at, id LIMIT 1"
        ).fetchone()
    if row is None:
        raise RuntimeError("no administrator account exists; bootstrap one before migration")
    return str(row[0])


def _checkpoint_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    tables: list[str] = []
    for (name,) in rows:
        cols = {row[1] for row in conn.execute(f'PRAGMA table_info("{name}")')}
        if "thread_id" in cols:
            tables.append(str(name))
    return tables


def _backup_checkpoint_sqlite(
    conn: sqlite3.Connection,
    db_path: Path,
) -> Path:
    """Create a fresh transactionally consistent snapshot, including WAL data."""
    backup = db_path.with_name(
        f"{db_path.name}.pre-tenant-migration-{uuid.uuid4().hex}.bak"
    )
    with sqlite3.connect(backup) as destination:
        conn.backup(destination)
    return backup


def _checkpoint_completed_destinations(
    conn: sqlite3.Connection,
    target_user_id: str,
    present_ids: set[str],
) -> set[str]:
    """Return destinations proven by the migration journal and current DB state."""
    from careercrew_core.state.checkpointer import tenant_thread_id

    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (_CHECKPOINT_MIGRATION_TABLE,),
    ).fetchone()
    if exists is None:
        return set()
    rows = conn.execute(
        f'SELECT source_thread_id, destination_thread_id FROM "{_CHECKPOINT_MIGRATION_TABLE}" '
        "WHERE target_user_id=?",
        (target_user_id,),
    ).fetchall()
    completed: set[str] = set()
    for source_id, destination_id in rows:
        source = str(source_id)
        destination = str(destination_id)
        if destination != tenant_thread_id(target_user_id, source):
            continue
        if destination in present_ids:
            completed.add(destination)
    return completed


def _ensure_checkpoint_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f'CREATE TABLE IF NOT EXISTS "{_CHECKPOINT_MIGRATION_TABLE}" ('
        "target_user_id TEXT NOT NULL, "
        "source_thread_id TEXT NOT NULL, "
        "destination_thread_id TEXT NOT NULL, "
        "PRIMARY KEY (target_user_id, source_thread_id)"
        ")"
    )


def migrate_checkpoint_sqlite(
    path: str | Path,
    target_user_id: str,
    *,
    apply: bool = False,
) -> MigrationResult:
    """Namespace every legacy LangGraph thread id in a SQLite checkpointer."""
    from careercrew_core.state.checkpointer import tenant_thread_id

    db_path = Path(path)
    result = MigrationResult()
    if not db_path.is_file():
        result.messages.append(f"SKIP checkpoint (missing): {db_path}")
        return result
    conn = sqlite3.connect(db_path)
    try:
        tables = _checkpoint_tables(conn)
        all_ids: set[str] = set()
        for table in tables:
            rows = conn.execute(f'SELECT DISTINCT thread_id FROM "{table}"').fetchall()
            all_ids.update(str(row[0]) for row in rows if row[0])

        # Migration status is durable data, not a string-prefix guess.  This is
        # necessary because every possible string (including one identical to
        # the internal encoding shape) is a valid public thread ID.
        migrated_ids = _checkpoint_completed_destinations(
            conn, target_user_id, all_ids,
        )
        migration_ids: list[str] = []
        for public_id in sorted(all_ids - migrated_ids):
            internal_id = tenant_thread_id(target_user_id, public_id)
            collision = any(
                conn.execute(
                    f'SELECT 1 FROM "{table}" WHERE thread_id=? LIMIT 1', (internal_id,)
                ).fetchone()
                for table in tables
            )
            if collision:
                result.conflicts += 1
                result.messages.append(
                    f"CONFLICT checkpoint thread {public_id!r}: destination already exists"
                )
                continue
            result.changed += 1
            migration_ids.append(public_id)
            mode = "APPLY" if apply else "DRY-RUN"
            result.messages.append(f"{mode} checkpoint {public_id!r} -> {internal_id!r}")

        if apply and migration_ids:
            backup = _backup_checkpoint_sqlite(conn, db_path)
            result.messages.append(f"BACKUP checkpoint -> {backup}")
            _ensure_checkpoint_migration_table(conn)
            for public_id in migration_ids:
                internal_id = tenant_thread_id(target_user_id, public_id)
                for table in tables:
                    conn.execute(
                        f'UPDATE "{table}" SET thread_id=? WHERE thread_id=?',
                        (internal_id, public_id),
                    )
                conn.execute(
                    f'INSERT OR REPLACE INTO "{_CHECKPOINT_MIGRATION_TABLE}" '
                    "(target_user_id, source_thread_id, destination_thread_id) VALUES (?, ?, ?)",
                    (target_user_id, public_id, internal_id),
                )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return result


def _resume_thread_destination(root: Path, user_id: str, public_id: str) -> Path:
    digest = hashlib.sha256(public_id.encode("utf-8")).hexdigest()
    return root / user_id / f"{digest}.txt"


def migrate_local_resume_assets(
    data_dir: str | Path,
    target_user_id: str,
    *,
    apply: bool = False,
) -> MigrationResult:
    """Copy legacy flat thread resumes and attribute legacy library metadata."""
    if re.fullmatch(r"u_[A-Za-z0-9]+", target_user_id) is None:
        raise ValueError(f"unsafe target user id: {target_user_id!r}")
    root = Path(data_dir)
    thread_root = root / "uploads" / "resume_threads"
    library_root = root / "uploads" / "resumes"
    result = MigrationResult()

    if thread_root.is_dir():
        for source in sorted(thread_root.glob("*.txt")):
            destination = _resume_thread_destination(thread_root, target_user_id, source.stem)
            if destination.is_file():
                if destination.read_bytes() != source.read_bytes():
                    result.conflicts += 1
                    result.messages.append(f"CONFLICT resume thread destination: {destination}")
                continue
            result.changed += 1
            mode = "APPLY" if apply else "DRY-RUN"
            result.messages.append(f"{mode} copy resume thread {source} -> {destination}")
            if apply:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)  # deliberately preserve the legacy source

    if library_root.is_dir():
        for meta_path in sorted(library_root.glob("*.json")):
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as err:
                result.conflicts += 1
                result.messages.append(f"CONFLICT unreadable resume metadata {meta_path}: {err}")
                continue
            owner = metadata.get("user_id")
            if owner not in (None, "", LEGACY_USER_ID) or owner == target_user_id:
                continue
            result.changed += 1
            mode = "APPLY" if apply else "DRY-RUN"
            result.messages.append(f"{mode} attribute resume {meta_path.name} -> {target_user_id}")
            if apply:
                backup = meta_path.with_name(meta_path.name + ".pre-tenant-migration.bak")
                if not backup.exists():
                    shutil.copy2(meta_path, backup)
                metadata["user_id"] = target_user_id
                temp = meta_path.with_name(meta_path.name + ".tenant-migration.tmp")
                temp.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
                temp.replace(meta_path)
    return result


def migrate_qdrant_client(
    client,
    collections: Iterable[str],
    target_user_id: str,
    *,
    apply: bool = False,
) -> MigrationResult:
    """Re-key legacy Qdrant points while preserving payload._id domain ids."""
    from qdrant_client.models import PointIdsList, PointStruct

    from careercrew_ai.vector_store.qdrant_store import QdrantStore

    def normalize(value):
        if hasattr(value, "model_dump"):
            value = value.model_dump(exclude_none=True)
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        return value

    def destination_matches(point, payload: dict, vector) -> bool:
        return normalize(point.payload or {}) == normalize(payload) and normalize(
            point.vector or {},
        ) == normalize(vector or {})

    result = MigrationResult()
    for collection in dict.fromkeys(collections):
        if not collection or not client.collection_exists(collection):
            result.messages.append(f"SKIP Qdrant collection (missing): {collection}")
            continue
        offset = None
        all_points = []
        while True:
            points, offset = client.scroll(
                collection,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            all_points.extend(points)
            if offset is None:
                break
        for point in all_points:
            payload = dict(point.payload or {})
            logical_id = str(payload.get("_id") or point.id)
            owner = payload.get("user_id")
            if owner not in (None, "", LEGACY_USER_ID, target_user_id):
                continue
            expected_id = QdrantStore._to_qid(logical_id, target_user_id)
            if owner == target_user_id and str(point.id) == expected_id:
                continue
            expected_payload = dict(payload)
            expected_payload["_id"] = logical_id
            expected_payload["user_id"] = target_user_id
            destination_ready = False
            if str(point.id) != expected_id:
                existing = client.retrieve(
                    collection,
                    ids=[expected_id],
                    with_payload=True,
                    with_vectors=True,
                )
                if existing:
                    if not destination_matches(existing[0], expected_payload, point.vector):
                        result.conflicts += 1
                        result.messages.append(
                            f"CONFLICT Qdrant {collection}/{logical_id}: destination differs"
                        )
                        continue
                    destination_ready = True
            result.changed += 1
            mode = "APPLY" if apply else "DRY-RUN"
            action = "cleanup" if destination_ready else "migrate"
            result.messages.append(f"{mode} Qdrant {action} {collection}/{logical_id}")
            if apply:
                if not destination_ready:
                    client.upsert(
                        collection,
                        points=[PointStruct(
                            id=expected_id,
                            vector=point.vector,
                            payload=expected_payload,
                        )],
                        wait=True,
                    )
                    copied = client.retrieve(
                        collection,
                        ids=[expected_id],
                        with_payload=True,
                        with_vectors=True,
                    )
                    if not copied or not destination_matches(
                        copied[0], expected_payload, point.vector,
                    ):
                        raise RuntimeError(
                            f"Qdrant copy verification failed: {collection}/{logical_id}"
                        )
                if str(point.id) != expected_id:
                    client.delete(
                        collection,
                        points_selector=PointIdsList(points=[point.id]),
                        wait=True,
                    )
                    if client.retrieve(collection, ids=[point.id]):
                        raise RuntimeError(
                            f"Qdrant source cleanup verification failed: "
                            f"{collection}/{logical_id}"
                        )
    return result


def migrate_postgres(
    dsn: str,
    target_user_id: str,
    *,
    apply: bool = False,
) -> MigrationResult:
    """Transactionally move legacy rows when the first admin is not u_001."""
    result = MigrationResult()
    if not dsn or target_user_id == LEGACY_USER_ID:
        return result
    import psycopg

    tables = {
        "episodic_events": "id",
        "semantic_facts": "name",
        "user_memory_policy": "user_id",
        "threads": "thread_id",
    }
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            existing_tables: dict[str, str] = {}
            for table, key in tables.items():
                cur.execute("SELECT to_regclass(%s)", (table,))
                if cur.fetchone()[0] is None:
                    continue
                existing_tables[table] = key
                if key == "user_id":
                    cur.execute(f"SELECT 1 FROM {table} WHERE user_id=%s", (target_user_id,))
                else:
                    cur.execute(
                        f"SELECT 1 FROM {table} s JOIN {table} d ON s.{key}=d.{key} "
                        "WHERE s.user_id=%s AND d.user_id=%s LIMIT 1",
                        (LEGACY_USER_ID, target_user_id),
                    )
                if cur.fetchone() is not None:
                    result.conflicts += 1
                    result.messages.append(f"CONFLICT Postgres table {table}: target keys exist")
            if result.conflicts:
                conn.rollback()
                return result
            for table in existing_tables:
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=%s", (LEGACY_USER_ID,))
                count = int(cur.fetchone()[0])
                if count:
                    result.changed += count
                    result.messages.append(
                        f"{'APPLY' if apply else 'DRY-RUN'} Postgres {table}: {count} rows"
                    )
                    if apply:
                        cur.execute(
                            f"UPDATE {table} SET user_id=%s WHERE user_id=%s",
                            (target_user_id, LEGACY_USER_ID),
                        )
            if apply:
                conn.commit()
            else:
                conn.rollback()
    return result


def _qdrant_from_settings():
    from qdrant_client import QdrantClient

    from careercrew_core.state.settings import load_settings

    settings = load_settings()
    cfg = settings.vector_store
    url = (cfg.url or "").strip()
    if url == ":memory:":
        client = QdrantClient(":memory:")
    elif url:
        client = QdrantClient(url=url, api_key=cfg.api_key or None)
    else:
        client = QdrantClient(":memory:")
    collections = [*cfg.collections.values(), settings.memory.episodic.collection]
    return client, collections


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply changes; default is dry-run")
    parser.add_argument("--target-user", default="", help="explicit target instead of first admin")
    parser.add_argument("--account-db", default="", help="accounts SQLite path")
    parser.add_argument("--checkpoint-db", default=str(PROJECT_ROOT / "data/db/checkpointer.db"))
    parser.add_argument("--data-dir", default=str(PROJECT_ROOT / "data"))
    parser.add_argument("--skip-qdrant", action="store_true")
    parser.add_argument("--postgres-dsn", default="", help="optional explicit memory DB DSN")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(PROJECT_ROOT))
    if args.target_user:
        target = args.target_user
    else:
        if args.account_db:
            account_db = Path(args.account_db)
        else:
            from careercrew_core.state.settings import load_auth_settings

            account_db = Path(load_auth_settings().account_db_path)
        target = first_admin_id(account_db)

    total = MigrationResult()
    total.extend(migrate_checkpoint_sqlite(args.checkpoint_db, target, apply=args.apply))
    total.extend(migrate_local_resume_assets(args.data_dir, target, apply=args.apply))
    if args.postgres_dsn:
        total.extend(migrate_postgres(args.postgres_dsn, target, apply=args.apply))
    qdrant_failed = False
    if not args.skip_qdrant:
        try:
            client, collections = _qdrant_from_settings()
            total.extend(migrate_qdrant_client(client, collections, target, apply=args.apply))
        except Exception as err:
            qdrant_failed = True
            total.messages.append(f"ERROR Qdrant: {type(err).__name__}: {err}")

    print(f"mode={'APPLY' if args.apply else 'DRY-RUN'} target_user={target}")
    for message in total.messages:
        print("-", message)
    print(f"changes={total.changed} conflicts={total.conflicts}")
    if qdrant_failed:
        return 3
    return 2 if total.conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
