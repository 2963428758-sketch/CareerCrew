"""Tests for the automated backup and restore-drill helpers."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import backup_restore


def _fake_dump(config, output_path: Path) -> None:
    output_path.write_bytes(b"synthetic postgres custom dump")


def _fake_snapshots(qdrant_url: str, collections: list[str], output_dir: Path):
    del qdrant_url
    result = []
    for collection in collections:
        path = output_dir / "qdrant" / f"{collection}.snapshot"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"snapshot:{collection}".encode())
        result.append(
            backup_restore.SnapshotArtifact(
                collection=collection,
                snapshot=f"{collection}.snapshot",
                path=path,
                point_count=2,
            )
        )
    return result


def _create_backup(tmp_path: Path, *, collections: list[str] | None = None) -> Path:
    return backup_restore.create_backup(
        database_url="postgresql://backup_user:super-secret@db.example:5433/careercrew?sslmode=require",
        qdrant_url="http://qdrant.example:6333",
        backup_root=tmp_path / "backups",
        uploads_dir=tmp_path / "data" / "uploads",
        parsed_dir=tmp_path / "data" / "parsed",
        collections=collections if collections is not None else ["careercrew_mm"],
        now=datetime(2026, 9, 9, 2, 0, 0, tzinfo=UTC),
        pg_dump_runner=_fake_dump,
        qdrant_snapshotter=_fake_snapshots,
    )


def test_parse_database_url_keeps_password_internal_and_never_in_dump_argv() -> None:
    config = backup_restore.parse_database_url(
        "postgresql://backup_user:super-secret@db.example:5433/careercrew?sslmode=require"
    )

    command = backup_restore.pg_dump_command(config, Path("/tmp/careercrew.dump"))

    assert config.password == "super-secret"
    assert config.host == "db.example"
    assert config.port == 5433
    assert config.database == "careercrew"
    assert "super-secret" not in command
    assert "super-secret" not in backup_restore.redacted_database_identifier(config)


def test_create_backup_manifest_records_size_hash_and_point_count(tmp_path: Path) -> None:
    uploads = tmp_path / "data" / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "resume.txt").write_text("synthetic", encoding="utf-8")

    backup_dir = _create_backup(tmp_path)
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))

    artifact_names = {item["path"] for item in manifest["artifacts"]}
    assert "postgres.dump" in artifact_names
    assert "files.zip" in artifact_names
    assert "qdrant/careercrew_mm.snapshot" in artifact_names
    assert all(item["size"] > 0 and len(item["sha256"]) == 64 for item in manifest["artifacts"])
    assert manifest["qdrant"][0]["point_count"] == 2
    assert manifest["database"] == {
        "host": "db.example",
        "port": 5433,
        "database": "careercrew",
        "user": "backup_user",
    }


def test_verify_backup_rejects_changed_artifact(tmp_path: Path) -> None:
    backup_dir = _create_backup(tmp_path, collections=[])
    (backup_dir / "postgres.dump").write_bytes(b"changed")

    with pytest.raises(backup_restore.BackupValidationError, match="sha256|size"):
        backup_restore.verify_backup(backup_dir, check_pg_restore=False)


def test_verify_backup_rejects_undeclared_qdrant_manifest_artifact(tmp_path: Path) -> None:
    backup_dir = _create_backup(tmp_path)
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["qdrant"][0]["path"] = "qdrant/unhashed.snapshot"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(backup_restore.BackupValidationError, match="Qdrant.*artifact"):
        backup_restore.verify_backup(backup_dir, check_pg_restore=False)


def test_restore_drill_attempts_database_cleanup_when_restore_fails(tmp_path: Path, monkeypatch) -> None:
    backup_dir = _create_backup(tmp_path, collections=[])
    admin_calls: list[str] = []

    def fake_admin(database_url: str, sql: str) -> None:
        del database_url
        admin_calls.append(sql)

    def fail_restore(*args, **kwargs) -> None:
        raise backup_restore.BackupValidationError("synthetic restore failure")

    monkeypatch.setattr(backup_restore, "_execute_admin", fake_admin)
    monkeypatch.setattr(backup_restore, "restore_postgres_dump", fail_restore)

    with pytest.raises(backup_restore.BackupValidationError, match="synthetic restore failure"):
        backup_restore.restore_drill(
            backup_dir,
            database_url="postgresql://backup_user:secret@db.example:5433/careercrew",
            now=datetime(2026, 9, 9, 3, 0, 0, tzinfo=UTC),
        )

    assert any(sql.startswith('DROP DATABASE IF EXISTS "careercrew_restore_') for sql in admin_calls)


def test_restore_drill_surfaces_database_cleanup_failure(tmp_path: Path, monkeypatch) -> None:
    backup_dir = _create_backup(tmp_path, collections=[])
    calls = 0

    def fake_admin(database_url: str, sql: str) -> None:
        nonlocal calls
        del database_url
        calls += 1
        if sql.startswith("DROP DATABASE"):
            raise backup_restore.BackupValidationError("synthetic cleanup failure")

    def fail_restore(*args, **kwargs) -> None:
        raise backup_restore.BackupValidationError("synthetic restore failure")

    monkeypatch.setattr(backup_restore, "_execute_admin", fake_admin)
    monkeypatch.setattr(backup_restore, "restore_postgres_dump", fail_restore)

    with pytest.raises(backup_restore.BackupValidationError, match="cleanup failure"):
        backup_restore.restore_drill(
            backup_dir,
            database_url="postgresql://backup_user:secret@db.example:5433/careercrew",
            now=datetime(2026, 9, 9, 3, 0, 1, tzinfo=UTC),
        )

    assert calls == 2


def test_prune_backups_only_removes_old_exact_backup_children(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    root.mkdir()
    old = root / "careercrew-20200101-000000"
    fresh = root / "careercrew-20260908-000000"
    arbitrary = root / "careercrew-20200101-000000.tmp"
    for path in (old, fresh, arbitrary):
        path.mkdir()
        (path / "marker").write_text("x", encoding="utf-8")
    source = tmp_path / "data" / "uploads"
    source.mkdir(parents=True)
    (source / "keep.txt").write_text("keep", encoding="utf-8")

    removed = backup_restore.prune_backups(
        root,
        retention_days=30,
        now=datetime(2026, 9, 9, tzinfo=UTC),
    )

    assert removed == [old]
    assert not old.exists()
    assert fresh.exists()
    assert arbitrary.exists()
    assert source.exists()


@pytest.mark.parametrize(
    "target",
    ["careercrew", "postgres", "../careercrew_restore_bad", "careercrew_restore_bad/path"],
)
def test_validate_restore_target_rejects_source_root_and_path_traversal(target: str) -> None:
    with pytest.raises(backup_restore.BackupValidationError):
        backup_restore.validate_restore_target(target, "careercrew")


def test_validate_restore_target_accepts_generated_temporary_name() -> None:
    backup_restore.validate_restore_target(
        "careercrew_restore_20260909120000",
        "careercrew",
    )
