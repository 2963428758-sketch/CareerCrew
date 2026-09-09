"""Automated, verifiable CareerCrew backups and isolated restore drills.

The PostgreSQL password is kept in a parsed DSN object and passed to child
processes only through ``PGPASSWORD``.  It is never included in command-line
arguments, manifests, or operator output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_ROOT = ROOT / "data" / "backups"
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_COLLECTIONS = ("careercrew_mm", "careercrew_episodic_v2")
BACKUP_NAME_RE = re.compile(r"^careercrew-(?P<stamp>\d{8}-\d{6})$")
RESTORE_NAME_RE = re.compile(r"^careercrew_restore_[a-z0-9_]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COLLECTION_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class BackupValidationError(ValueError):
    """Raised when a backup, path, or restore target is unsafe or invalid."""


@dataclass(frozen=True)
class DatabaseConfig:
    scheme: str
    user: str
    host: str
    port: int
    database: str
    password: str = field(repr=False)
    options: Mapping[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class SnapshotArtifact:
    collection: str
    snapshot: str
    path: Path
    point_count: int | None = None


def parse_database_url(value: str) -> DatabaseConfig:
    """Parse a PostgreSQL DSN without exposing its password in the result repr."""

    if not isinstance(value, str) or not value.strip():
        raise BackupValidationError("DATABASE_URL is required")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise BackupValidationError("DATABASE_URL must use a PostgreSQL scheme")
    if not parsed.username or not parsed.hostname:
        raise BackupValidationError("DATABASE_URL must include a username and host")
    try:
        port = parsed.port or 5432
    except ValueError as exc:
        raise BackupValidationError("DATABASE_URL has an invalid port") from exc
    database = unquote(parsed.path.lstrip("/"))
    if not database or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,62}", database):
        raise BackupValidationError("DATABASE_URL has an unsafe database name")
    return DatabaseConfig(
        scheme=parsed.scheme,
        user=unquote(parsed.username),
        host=parsed.hostname,
        port=port,
        database=database,
        password=unquote(parsed.password or ""),
        options={key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()},
    )


def redacted_database_identifier(config: DatabaseConfig) -> str:
    """Return a password-free database identifier suitable for manifests/output."""

    host = config.host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{config.scheme}://{quote(config.user, safe='')}@{host}:{config.port}/{quote(config.database, safe='')}"


def _database_url_for(config: DatabaseConfig, database: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,62}", database):
        raise BackupValidationError("unsafe PostgreSQL database target")
    host = config.host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    user = quote(config.user, safe="")
    password = quote(config.password, safe="")
    query = "&".join(
        f"{quote(key, safe='')}={quote(value, safe='')}"
        for key, value in config.options.items()
    )
    auth = f"{user}:{password}@" if config.password else f"{user}@"
    return urlunsplit((config.scheme, auth + host + f":{config.port}", f"/{database}", query, ""))


def pg_dump_command(config: DatabaseConfig, output_path: Path) -> list[str]:
    """Build a pg_dump argv with no password-bearing argument."""

    return [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--host",
        config.host,
        "--port",
        str(config.port),
        "--username",
        config.user,
        "--dbname",
        config.database,
        "--file",
        str(Path(output_path)),
    ]


def _child_env(config: DatabaseConfig) -> dict[str, str]:
    env = os.environ.copy()
    env["PGPASSWORD"] = config.password
    for key in ("sslmode", "connect_timeout", "application_name"):
        if config.options.get(key):
            env_key = "PG" + key.upper()
            env[env_key] = config.options[key]
    return env


def _compact_error(value: str) -> str:
    value = re.sub(r"(postgres(?:ql)?(?:\+[^:]+)?://[^:/@]+:)[^@]+(@)", r"\1***\2", value)
    return " ".join(value.split())[-500:]


def run_pg_dump(config: DatabaseConfig, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(  # noqa: S603 -- argv is built from parsed non-secret fields
        pg_dump_command(config, output_path),
        cwd=ROOT,
        env=_child_env(config),
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise BackupValidationError(f"pg_dump failed: {_compact_error(process.stderr or process.stdout)}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise BackupValidationError("pg_dump did not create a non-empty dump")


def _safe_filename(value: str, fallback: str) -> str:
    value = Path(str(value)).name
    value = re.sub(r"[^A-Za-z0-9_.-]", "_", value)
    return value or fallback


def _qdrant_json(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        value = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise BackupValidationError(f"Qdrant {operation} failed") from exc
    if not isinstance(value, dict):
        raise BackupValidationError(f"Qdrant {operation} returned an invalid response")
    return value


def create_qdrant_snapshots(
    qdrant_url: str,
    collections: Sequence[str],
    output_dir: Path,
    *,
    timeout: float = 30.0,
) -> list[SnapshotArtifact]:
    """Create, download, and clean up one Qdrant snapshot per collection."""

    base_url = qdrant_url.rstrip("/")
    snapshots: list[SnapshotArtifact] = []
    session = requests.Session()
    for collection in collections:
        if not COLLECTION_RE.fullmatch(collection):
            raise BackupValidationError(f"unsafe Qdrant collection name: {collection!r}")
        encoded = quote(collection, safe="")
        try:
            info_response = session.get(
                f"{base_url}/collections/{encoded}", timeout=timeout
            )
            info = _qdrant_json(info_response, f"collection info {collection}")
            info_result = info.get("result") or {}
            point_count = info_result.get("points_count")
            create_response = session.post(
                f"{base_url}/collections/{encoded}/snapshots", timeout=timeout
            )
            created = _qdrant_json(create_response, f"snapshot create {collection}")
            created_result = created.get("result") or {}
            snapshot_name = created_result.get("name")
            if not isinstance(snapshot_name, str) or not snapshot_name:
                raise BackupValidationError(f"Qdrant snapshot name missing for {collection}")
            snapshot_file = _safe_filename(snapshot_name, f"{collection}.snapshot")
            local_path = output_dir / "qdrant" / f"{_safe_filename(collection, 'collection')}_{snapshot_file}"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            download_response = session.get(
                f"{base_url}/collections/{encoded}/snapshots/{quote(snapshot_name, safe='')}",
                timeout=timeout,
            )
            try:
                download_response.raise_for_status()
                local_path.write_bytes(download_response.content)
            except (requests.RequestException, OSError) as exc:
                raise BackupValidationError(f"Qdrant snapshot download failed for {collection}") from exc
            finally:
                try:
                    session.delete(
                        f"{base_url}/collections/{encoded}/snapshots/{quote(snapshot_name, safe='')}",
                        timeout=timeout,
                    )
                except requests.RequestException:
                    # The downloaded artifact remains valid; an operator can
                    # remove a server-side snapshot during routine cleanup.
                    pass
            snapshots.append(
                SnapshotArtifact(
                    collection=collection,
                    snapshot=snapshot_name,
                    path=local_path,
                    point_count=int(point_count) if point_count is not None else None,
                )
            )
        except requests.RequestException as exc:
            raise BackupValidationError(f"Qdrant request failed for {collection}") from exc
    return snapshots


def _iter_source_files(source: Path) -> list[Path]:
    if not source.exists():
        return []
    root = source.resolve()
    if not source.is_dir():
        raise BackupValidationError(f"backup source is not a directory: {source}")
    files: list[Path] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_file() and root in path.resolve().parents:
            files.append(path)
    return files


def archive_data_sources(
    output_path: Path,
    uploads_dir: Path,
    parsed_dir: Path,
) -> None:
    """Archive only uploads and parsed data with fixed safe archive prefixes."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, prefix in ((Path(uploads_dir), "data/uploads"), (Path(parsed_dir), "data/parsed")):
            for path in _iter_source_files(source):
                relative = path.relative_to(source.resolve()).as_posix()
                archive.write(path, f"{prefix}/{relative}")


def _artifact_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _resolve_backup_root(value: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    root = candidate.resolve()
    protected = {
        ROOT.resolve(),
        (ROOT / "data").resolve(),
        (ROOT / "data" / "uploads").resolve(),
        (ROOT / "data" / "parsed").resolve(),
    }
    if root in protected:
        raise BackupValidationError("backup root cannot be a source or repository root")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _relative_artifact(backup_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(backup_dir.resolve()).as_posix()
    except ValueError as exc:
        raise BackupValidationError("backup artifact escaped its run directory") from exc


def create_backup(
    *,
    database_url: str | None = None,
    qdrant_url: str | None = None,
    backup_root: Path | str | None = None,
    uploads_dir: Path | str | None = None,
    parsed_dir: Path | str | None = None,
    collections: Sequence[str] | None = None,
    retention_days: int | None = None,
    now: datetime | None = None,
    pg_dump_runner: Callable[[DatabaseConfig, Path], None] = run_pg_dump,
    qdrant_snapshotter: Callable[[str, Sequence[str], Path], list[SnapshotArtifact]] = create_qdrant_snapshots,
) -> Path:
    """Create a PostgreSQL, Qdrant, and upload/parsed backup run."""

    config = parse_database_url(database_url or os.getenv("DATABASE_URL", ""))
    root = _resolve_backup_root(Path(backup_root or os.getenv("BACKUP_ROOT", DEFAULT_BACKUP_ROOT)))
    qdrant_url = qdrant_url or os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL)
    if retention_days is None:
        retention_days = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
    if retention_days < 1:
        raise BackupValidationError("BACKUP_RETENTION_DAYS must be at least 1")
    if collections is None:
        raw_collections = os.getenv("QDRANT_COLLECTIONS", ",".join(DEFAULT_COLLECTIONS))
        collections = [item.strip() for item in raw_collections.split(",") if item.strip()]
    if uploads_dir is None:
        uploads_dir = ROOT / "data" / "uploads"
    if parsed_dir is None:
        parsed_dir = ROOT / "data" / "parsed"

    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    run_dir = root / f"careercrew-{timestamp.strftime('%Y%m%d-%H%M%S')}"
    if run_dir.exists():
        raise BackupValidationError(f"backup run already exists: {run_dir.name}")
    run_dir.mkdir(parents=True)
    try:
        dump_path = run_dir / "postgres.dump"
        pg_dump_runner(config, dump_path)
        files_path = run_dir / "files.zip"
        archive_data_sources(files_path, Path(uploads_dir), Path(parsed_dir))
        snapshots = qdrant_snapshotter(qdrant_url, collections, run_dir)

        artifact_paths = [dump_path, files_path] + [snapshot.path for snapshot in snapshots]
        artifacts = []
        for path in artifact_paths:
            if not path.is_file():
                raise BackupValidationError(f"backup artifact is missing: {path.name}")
            size, sha256 = _artifact_digest(path)
            kind = "postgres" if path == dump_path else "files" if path == files_path else "qdrant_snapshot"
            artifacts.append({"kind": kind, "path": _relative_artifact(run_dir, path), "size": size, "sha256": sha256})
        manifest = {
            "format": "careercrew-backup-v1",
            "created_at": timestamp.isoformat(),
            "database": {
                "host": config.host,
                "port": config.port,
                "database": config.database,
                "user": config.user,
            },
            "qdrant": [
                {
                    "collection": snapshot.collection,
                    "snapshot": snapshot.snapshot,
                    "point_count": snapshot.point_count,
                    "path": _relative_artifact(run_dir, snapshot.path),
                }
                for snapshot in snapshots
            ],
            "retention_days": retention_days,
            "artifacts": artifacts,
        }
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verify_backup(run_dir, check_pg_restore=False)
        prune_backups(root, retention_days=retention_days, now=timestamp)
        return run_dir
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise


def _safe_backup_artifact(backup_dir: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise BackupValidationError("backup manifest contains an unsafe artifact path")
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts or ".." in windows.parts:
        raise BackupValidationError("backup manifest contains a path traversal")
    candidate = (backup_dir / Path(*posix.parts)).resolve()
    try:
        candidate.relative_to(backup_dir.resolve())
    except ValueError as exc:
        raise BackupValidationError("backup artifact escaped its run directory") from exc
    return candidate


def _validate_zip_members(zip_path: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise BackupValidationError(f"files archive is corrupt: {bad_member}")
            for member in archive.infolist():
                posix = PurePosixPath(member.filename)
                windows = PureWindowsPath(member.filename)
                if (
                    posix.is_absolute()
                    or windows.is_absolute()
                    or ".." in posix.parts
                    or ".." in windows.parts
                ):
                    raise BackupValidationError("files archive contains a path traversal")
    except zipfile.BadZipFile as exc:
        raise BackupValidationError("files archive is corrupt") from exc


def verify_backup(
    backup_dir: Path | str,
    *,
    check_pg_restore: bool = True,
) -> dict[str, Any]:
    """Verify manifest, artifact hashes/sizes, zip integrity, and pg_restore list."""

    backup_dir = Path(backup_dir).expanduser().resolve()
    if not BACKUP_NAME_RE.fullmatch(backup_dir.name) or not backup_dir.is_dir():
        raise BackupValidationError("backup path must be a generated careercrew-YYYYMMDD-HHMMSS directory")
    manifest_path = backup_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupValidationError("backup manifest cannot be read") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != "careercrew-backup-v1":
        raise BackupValidationError("backup manifest format is invalid")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise BackupValidationError("backup manifest has no artifacts")
    seen: set[str] = set()
    files_artifact: Path | None = None
    postgres_artifact: Path | None = None
    for item in artifacts:
        if not isinstance(item, dict):
            raise BackupValidationError("backup artifact entry is invalid")
        relative = item.get("path")
        if relative in seen:
            raise BackupValidationError("backup manifest contains duplicate artifact paths")
        seen.add(relative)
        path = _safe_backup_artifact(backup_dir, relative)
        if not path.is_file():
            raise BackupValidationError(f"backup artifact is missing: {relative}")
        size = item.get("size")
        sha256 = item.get("sha256")
        if not isinstance(size, int) or size < 0 or not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
            raise BackupValidationError(f"backup artifact metadata is invalid: {relative}")
        actual_size, actual_hash = _artifact_digest(path)
        if actual_size != size:
            raise BackupValidationError(f"backup artifact size mismatch: {relative}")
        if actual_hash != sha256:
            raise BackupValidationError(f"backup artifact sha256 mismatch: {relative}")
        if item.get("kind") == "files":
            files_artifact = path
        elif item.get("kind") == "postgres":
            postgres_artifact = path
    if files_artifact is None or postgres_artifact is None:
        raise BackupValidationError("backup must contain postgres and files artifacts")
    _validate_zip_members(files_artifact)
    if check_pg_restore:
        pg_restore = shutil.which("pg_restore")
        if pg_restore:
            process = subprocess.run(  # noqa: S603 -- path comes from PATH and artifact is confined above
                [pg_restore, "--list", str(postgres_artifact)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if process.returncode != 0:
                raise BackupValidationError(
                    f"pg_restore --list failed: {_compact_error(process.stderr or process.stdout)}"
                )
    return manifest


def prune_backups(
    backup_root: Path | str,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> list[Path]:
    """Remove only old, direct children with the exact generated backup name."""

    if retention_days < 1:
        raise BackupValidationError("retention_days must be at least 1")
    root = _resolve_backup_root(Path(backup_root))
    cutoff = (now or datetime.now(UTC)).astimezone(UTC) - timedelta(days=retention_days)
    removed: list[Path] = []
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        match = BACKUP_NAME_RE.fullmatch(candidate.name)
        if not match:
            continue
        try:
            created = datetime.strptime(match.group("stamp"), "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            continue
        if created < cutoff:
            resolved = candidate.resolve()
            if resolved.parent != root.resolve():
                raise BackupValidationError("refusing to prune an escaped backup path")
            shutil.rmtree(resolved)
            removed.append(candidate)
    return removed


def validate_restore_target(target_database: str, source_database: str) -> str:
    """Allow only generated temporary restore database names, never the source."""

    if not isinstance(target_database, str):
        raise BackupValidationError("restore database name must be text")
    target = target_database.strip()
    if target.lower() == str(source_database).strip().lower():
        raise BackupValidationError("restore target must not be the source database")
    if len(target) > 63 or not RESTORE_NAME_RE.fullmatch(target) or ".." in target:
        raise BackupValidationError("restore target must be a generated temporary database name")
    return target


def pg_restore_command(
    config: DatabaseConfig,
    target_database: str,
    dump_path: Path,
) -> list[str]:
    return [
        "pg_restore",
        "--exit-on-error",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--host",
        config.host,
        "--port",
        str(config.port),
        "--username",
        config.user,
        "--dbname",
        target_database,
        str(Path(dump_path)),
    ]


def restore_postgres_dump(
    dump_path: Path | str,
    target_database: str,
    database: DatabaseConfig | str,
    *,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> None:
    """Restore a dump into a validated temporary database target."""

    config = parse_database_url(database) if isinstance(database, str) else database
    validate_restore_target(target_database, config.database)
    dump_path = Path(dump_path).expanduser().resolve()
    if not dump_path.is_file():
        raise BackupValidationError("PostgreSQL dump does not exist")
    command = pg_restore_command(config, target_database, dump_path)
    process_runner = runner or subprocess.run
    process = process_runner(
        command,
        cwd=ROOT,
        env=_child_env(config),
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise BackupValidationError(f"pg_restore failed: {_compact_error(process.stderr or process.stdout)}")


def _execute_admin(database_url: str, sql: str) -> None:
    try:
        import psycopg

        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(sql)
    except BackupValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - convert driver details to operator-safe error
        raise BackupValidationError(f"PostgreSQL administrative operation failed: {_compact_error(str(exc))}") from exc


def _extract_files_to_temp(files_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="careercrew-restore-") as temp_dir:
        target = Path(temp_dir)
        with zipfile.ZipFile(files_path) as archive:
            for member in archive.infolist():
                relative = _safe_backup_artifact(target, member.filename)
                if member.is_dir():
                    relative.mkdir(parents=True, exist_ok=True)
                    continue
                relative.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, relative.open("wb") as destination:
                    shutil.copyfileobj(source, destination)


def restore_qdrant_snapshots(
    backup_dir: Path,
    manifest: Mapping[str, Any],
    qdrant_url: str,
    qdrant_container: str,
    restore_stamp: str,
) -> None:
    """Recover snapshots into temporary collections and remove them in finally."""

    qdrant_entries = manifest.get("qdrant") or []
    if not isinstance(qdrant_entries, list):
        raise BackupValidationError("backup Qdrant manifest is invalid")
    base_url = qdrant_url.rstrip("/")
    temporary: list[tuple[str, str]] = []
    copied_remote_names: list[str] = []
    try:
        for entry in qdrant_entries:
            if not isinstance(entry, dict):
                raise BackupValidationError("backup Qdrant entry is invalid")
            collection = entry.get("collection")
            relative = entry.get("path")
            if not isinstance(collection, str) or not COLLECTION_RE.fullmatch(collection):
                raise BackupValidationError("backup Qdrant collection name is invalid")
            snapshot_path = _safe_backup_artifact(backup_dir, relative)
            remote_name = _safe_filename(f"careercrew_restore_{restore_stamp}_{snapshot_path.name}", "restore.snapshot")
            target_collection = _safe_filename(f"{collection}__restore__{restore_stamp}", "restore")[:200]
            copy_process = subprocess.run(  # noqa: S603 -- container/name are explicit operator inputs
                ["docker", "cp", str(snapshot_path), f"{qdrant_container}:/qdrant/storage/snapshots/{remote_name}"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if copy_process.returncode != 0:
                raise BackupValidationError("Qdrant snapshot copy to container failed")
            copied_remote_names.append(remote_name)
            encoded = quote(target_collection, safe="")
            response = requests.post(
                f"{base_url}/collections/{encoded}/snapshots/recover",
                json={"location": f"/qdrant/storage/snapshots/{remote_name}"},
                timeout=60,
            )
            _qdrant_json(response, f"snapshot recovery {collection}")
            temporary.append((target_collection, remote_name))
            info = _qdrant_json(
                requests.get(f"{base_url}/collections/{encoded}", timeout=30),
                f"restored collection info {collection}",
            )
            actual = (info.get("result") or {}).get("points_count")
            expected = entry.get("point_count")
            if expected is not None and int(actual or 0) != int(expected):
                raise BackupValidationError(f"Qdrant point count mismatch for {collection}")
    finally:
        for collection, _remote_name in temporary:
            try:
                requests.delete(f"{base_url}/collections/{quote(collection, safe='')}", timeout=30)
            except requests.RequestException:
                pass
        for remote_name in copied_remote_names:
            subprocess.run(  # noqa: S603 -- cleanup uses the same validated operator inputs
                ["docker", "exec", qdrant_container, "rm", "-f", f"/qdrant/storage/snapshots/{remote_name}"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )


def restore_drill(
    backup_dir: Path | str,
    *,
    database_url: str,
    qdrant_url: str | None = None,
    qdrant_container: str | None = None,
    now: datetime | None = None,
) -> str:
    """Restore into generated temporary targets and clean all targets in finally."""

    backup_dir = Path(backup_dir).expanduser().resolve()
    manifest = verify_backup(backup_dir)
    config = parse_database_url(database_url)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    target_database = f"careercrew_restore_{timestamp.strftime('%Y%m%d%H%M%S')}"
    validate_restore_target(target_database, config.database)
    admin_url = _database_url_for(config, "postgres")
    target_url = _database_url_for(config, target_database)
    dump_path = next(
        _safe_backup_artifact(backup_dir, item["path"])
        for item in manifest["artifacts"]
        if item.get("kind") == "postgres"
    )
    files_path = next(
        _safe_backup_artifact(backup_dir, item["path"])
        for item in manifest["artifacts"]
        if item.get("kind") == "files"
    )
    created = False
    try:
        _execute_admin(admin_url, f'CREATE DATABASE "{target_database}"')
        created = True
        restore_postgres_dump(dump_path, target_database, config)
        try:
            import psycopg

            with psycopg.connect(target_url) as connection:
                connection.execute("SELECT 1")
        except Exception as exc:  # noqa: BLE001 - operator-safe drill failure
            raise BackupValidationError(f"restored PostgreSQL verification failed: {_compact_error(str(exc))}") from exc
        _extract_files_to_temp(files_path)
        if qdrant_container:
            restore_qdrant_snapshots(
                backup_dir,
                manifest,
                qdrant_url or os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL),
                qdrant_container,
                timestamp.strftime("%Y%m%d%H%M%S"),
            )
    except BaseException:
        if created:
            try:
                _execute_admin(admin_url, f'DROP DATABASE IF EXISTS "{target_database}" WITH (FORCE)')
            except BackupValidationError:
                # Preserve the original drill failure; the cleanup attempt has
                # still been made and the operator can inspect the database.
                pass
        raise
    else:
        if created:
            _execute_admin(admin_url, f'DROP DATABASE IF EXISTS "{target_database}" WITH (FORCE)')
        return target_database


def _load_environment() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass


def main(argv: list[str] | None = None) -> int:
    _load_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="create a verified component backup")
    create_parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    create_parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL))
    create_parser.add_argument("--backup-root", default=os.getenv("BACKUP_ROOT", str(DEFAULT_BACKUP_ROOT)))
    create_parser.add_argument("--retention-days", type=int, default=int(os.getenv("BACKUP_RETENTION_DAYS", "30")))
    create_parser.add_argument("--collections", default=os.getenv("QDRANT_COLLECTIONS", ",".join(DEFAULT_COLLECTIONS)))

    verify_parser = subparsers.add_parser("verify", help="verify a generated backup directory")
    verify_parser.add_argument("backup_dir")

    drill_parser = subparsers.add_parser("restore-drill", help="restore into temporary targets and clean them up")
    drill_parser.add_argument("backup_dir")
    drill_parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    drill_parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL))
    drill_parser.add_argument("--qdrant-container", default=os.getenv("QDRANT_CONTAINER"))

    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            path = create_backup(
                database_url=args.database_url,
                qdrant_url=args.qdrant_url,
                backup_root=args.backup_root,
                collections=[item.strip() for item in args.collections.split(",") if item.strip()],
                retention_days=args.retention_days,
            )
            print(f"backup created and verified: {path}")
        elif args.command == "verify":
            verify_backup(args.backup_dir)
            print("backup verification: OK")
        else:
            target = restore_drill(
                args.backup_dir,
                database_url=args.database_url or "",
                qdrant_url=args.qdrant_url,
                qdrant_container=args.qdrant_container,
            )
            print(f"restore drill: OK ({target} cleaned)")
    except BackupValidationError as exc:
        print(f"backup operation failed: {_compact_error(str(exc))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
