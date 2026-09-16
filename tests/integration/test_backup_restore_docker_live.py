"""Opt-in real Docker backup drill; all records and targets are disposable.

Windows hosts without PostgreSQL client binaries use real pg_dump/pg_restore
inside the explicitly selected container. No schema or validation is mocked.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import requests

pytestmark = pytest.mark.skipif(
    os.getenv("CAREERCREW_DOCKER_BACKUP_TEST") != "1", reason="explicit Docker drill opt-in required",
)


def test_real_component_backup_restore(tmp_path, monkeypatch):
    import psycopg
    from dotenv import load_dotenv
    from psycopg import sql

    from scripts import backup_restore as backup

    load_dotenv(override=False)
    parts = urlsplit(os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://"))
    assert parts.hostname in {"localhost", "127.0.0.1"} and not parts.query
    container = os.environ.get("CAREERCREW_PG_CONTAINER", "postgres")
    backup._validate_docker_target(container)
    suffix = uuid.uuid4().hex[:12]
    source = "careercrew_backup_test_" + suffix
    collection = "careercrew_backup_test_" + suffix
    admin = urlunsplit(parts._replace(path="/postgres"))
    uri = urlunsplit(parts._replace(path="/" + source))
    qdrant = "http://127.0.0.1:6333"
    # Verify the selected container is the loopback server, not a different PG.
    with psycopg.connect(admin) as conn:
        server_id = str(conn.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
    selected_id = subprocess.check_output(
        ["docker", "exec", container, "psql", "-U", parts.username, "-d", "postgres", "-Atc",
         "SELECT system_identifier FROM pg_control_system()"], text=True,
    ).strip()
    assert server_id == selected_id
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(source)))
    collection_created = False
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                       env=dict(os.environ, DATABASE_URL=uri), check=True, capture_output=True)
        response = requests.put(f"{qdrant}/collections/{collection}",
                                json={"vectors": {"size": 2, "distance": "Cosine"}}, timeout=30)
        response.raise_for_status()
        collection_created = True
        requests.put(f"{qdrant}/collections/{collection}/points?wait=true", json={"points": [
            {"id": 1, "vector": [1.0, 0.0], "payload": {"owner_user_id": "backup-canary"}},
        ]}, timeout=30).raise_for_status()
        uploads, parsed = tmp_path / "uploads", tmp_path / "parsed"
        uploads.mkdir()
        parsed.mkdir()
        (uploads / "canary.txt").write_text("backup integrity canary", encoding="utf-8")
        (parsed / "canary.txt").write_text("parsed integrity canary", encoding="utf-8")

        def dump(config, output):
            assert config.database == source
            with output.open("wb") as stream:
                subprocess.run(["docker", "exec", container, "pg_dump", "-U", config.user,
                                "-d", source, "-Fc"], stdout=stream, check=True)

        real_restore = backup.restore_postgres_dump

        def restore(path, target, config):
            def runner(command, **kwargs):
                # Keep the production target/path validation; translate only IO.
                with Path(path).open("rb") as stream:
                    return subprocess.run(
                        ["docker", "exec", "-i", container, "pg_restore", "-U", config.user,
                         "-d", target, "--exit-on-error", "--no-owner", "--no-privileges"],
                        stdin=stream, capture_output=True, text=True,
                    )
            return real_restore(path, target, config, runner=runner)

        monkeypatch.setattr(backup, "restore_postgres_dump", restore)
        run = backup.create_backup(database_url=uri, qdrant_url=qdrant,
                                   backup_root=tmp_path / "backups", uploads_dir=uploads,
                                   parsed_dir=parsed, collections=[collection], pg_dump_runner=dump)
        manifest = backup.verify_backup(run)
        assert manifest["qdrant"][0]["point_count"] == 1
        assert len(manifest["files"]) == 2
        result = backup.restore_drill(run, database_url=uri, qdrant_url=qdrant)
        assert result["cleaned"] is True
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT 1 FROM pg_database WHERE datname=%s",
                                (result["temporary_database"],)).fetchone() is None
        names = [item["name"] for item in requests.get(f"{qdrant}/collections", timeout=30).json()["result"]["collections"]]
        assert collection in names
        assert not any(name.startswith(collection + "__restore_") for name in names)
    finally:
        if collection_created:
            requests.delete(f"{qdrant}/collections/{collection}", timeout=30).raise_for_status()
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(source)))
