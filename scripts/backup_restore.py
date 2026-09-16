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
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit

import requests

from careercrew_core.pg_pool import normalize_dsn

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_ROOT = ROOT / "data" / "backups"
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_COLLECTIONS = (
    "careercrew_mm",
    "careercrew_episodic_v2",
    "careercrew_workspace_messages",
)
OPTIONAL_QDRANT_COLLECTIONS = frozenset({"careercrew_workspace_messages"})
BACKUP_NAME_RE = re.compile(r"^careercrew-(?P<stamp>\d{8}-\d{6})$")
RESTORE_NAME_RE = re.compile(r"^careercrew_restore_[a-z0-9_]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COLLECTION_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
DOCKER_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


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

    if any(os.environ.get(key) for key in (
        "PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS",
    )):
        raise BackupValidationError("inherited PostgreSQL routing overrides are unsupported")

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
    return normalize_dsn(urlunsplit((config.scheme, auth + host + f":{config.port}", f"/{database}", query, "")))


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
    if shutil.which("pg_dump") is None:
        # 主机没有 PostgreSQL 客户端时回退到 Docker 容器内的 pg_dump（与 Qdrant
        # 快照回退一致）。容器内走本地 socket 认证，因此 argv 不携带密码。
        container = resolve_pg_container(os.getenv("CAREERCREW_PG_CONTAINER"))
        with output_path.open("wb") as stream:
            process = subprocess.run(  # noqa: S603 -- argv is built from parsed non-secret fields
                [
                    "docker",
                    "exec",
                    container,
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "--username",
                    config.user,
                    "--dbname",
                    config.database,
                ],
                cwd=ROOT,
                stdout=stream,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        if process.returncode != 0:
            raise BackupValidationError(
                f"pg_dump failed: {_compact_error(process.stderr or '')}"
            )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise BackupValidationError("pg_dump did not create a non-empty dump")
        return
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


def _qdrant_headers(
    api_key: str | None = None, *, allow_environment: bool = True,
) -> dict[str, str]:
    """Build Qdrant auth headers without placing the key in a URL or argv."""

    key = str(
        api_key
        if api_key is not None
        else (os.getenv("QDRANT_API_KEY", "") if allow_environment else "")
    ).strip()
    return {"api-key": key} if key else {}


def create_qdrant_snapshots(
    qdrant_url: str,
    collections: Sequence[str],
    output_dir: Path,
    *,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[SnapshotArtifact]:
    """Create, download, and clean up one Qdrant snapshot per collection."""

    base_url = qdrant_url.rstrip("/")
    snapshots: list[SnapshotArtifact] = []
    session = requests.Session()
    headers = _qdrant_headers(api_key)
    for collection in collections:
        if not COLLECTION_RE.fullmatch(collection):
            raise BackupValidationError(f"unsafe Qdrant collection name: {collection!r}")
        encoded = quote(collection, safe="")
        try:
            info_response = session.get(
                f"{base_url}/collections/{encoded}", headers=headers, timeout=timeout
            )
            if info_response.status_code == 404 and collection in OPTIONAL_QDRANT_COLLECTIONS:
                # Conversation search creates its projection lazily.  A fresh
                # deployment with no semantic-search request yet has no data
                # to snapshot for this optional collection.
                continue
            info = _qdrant_json(info_response, f"collection info {collection}")
            info_result = info.get("result") or {}
            point_count = info_result.get("points_count")
            create_response = session.post(
                f"{base_url}/collections/{encoded}/snapshots", headers=headers, timeout=timeout
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
                headers=headers, timeout=timeout,
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
                        headers=headers, timeout=timeout,
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
) -> list[dict[str, Any]]:
    """Archive only uploads and parsed data with fixed safe archive prefixes."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, prefix in ((Path(uploads_dir), "data/uploads"), (Path(parsed_dir), "data/parsed")):
            for path in _iter_source_files(source):
                relative = path.relative_to(source.resolve()).as_posix()
                archive_name = f"{prefix}/{relative}"
                archive.write(path, archive_name)
                size, sha256 = _artifact_digest(path)
                manifest.append({"path": archive_name, "size": size, "sha256": sha256})
    return manifest


def _artifact_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _absolute_path(value: Path | str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate.resolve()


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _resolve_backup_root(value: Path, *, source_dirs: Sequence[Path | str] = ()) -> Path:
    root = _absolute_path(value)
    protected_roots = {
        ROOT.resolve(),
        (ROOT / "data").resolve(),
    }
    default_sources = (
        ROOT / "data" / "uploads",
        ROOT / "data" / "parsed",
    )
    source_roots = [_absolute_path(path) for path in (*default_sources, *source_dirs)]
    if root in protected_roots:
        raise BackupValidationError("backup root cannot be a repository or data root")
    if any(_paths_overlap(root, source) for source in source_roots):
        raise BackupValidationError("backup root cannot overlap a backup source")
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
    root = _resolve_backup_root(
        Path(backup_root or os.getenv("BACKUP_ROOT", DEFAULT_BACKUP_ROOT)),
        source_dirs=(Path(uploads_dir), Path(parsed_dir)),
    )

    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    run_dir = root / f"careercrew-{timestamp.strftime('%Y%m%d-%H%M%S')}"
    if run_dir.exists():
        raise BackupValidationError(f"backup run already exists: {run_dir.name}")
    run_dir.mkdir(parents=True)
    try:
        dump_path = run_dir / "postgres.dump"
        pg_dump_runner(config, dump_path)
        files_path = run_dir / "files.zip"
        files_manifest = archive_data_sources(files_path, Path(uploads_dir), Path(parsed_dir))
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
            "format": "careercrew-backup-v2",
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
            "files": files_manifest,
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
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(set(names)) != len(names):
                raise BackupValidationError("files archive contains duplicate members")
            for member in members:
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


def _validate_file_manifest_archive(files_path: Path, manifest: Mapping[str, Any]) -> None:
    """Verify every archived upload/parsed file against its independent digest."""

    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise BackupValidationError("backup file manifest is missing")
    expected: dict[str, tuple[int, str]] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise BackupValidationError("backup file manifest entry is invalid")
        relative = item.get("path")
        size = item.get("size")
        sha256 = item.get("sha256")
        if (
            not isinstance(relative, str)
            or not (relative.startswith("data/uploads/") or relative.startswith("data/parsed/"))
            or "\\" in relative
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(sha256, str)
            or not SHA256_RE.fullmatch(sha256)
            or relative in expected
        ):
            raise BackupValidationError("backup file manifest entry is invalid")
        expected[relative] = (size, sha256)
    try:
        with zipfile.ZipFile(files_path) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if len({member.filename for member in members}) != len(members):
                raise BackupValidationError("files archive contains duplicate members")
            actual_members = {
                member.filename for member in members
            }
            if actual_members != set(expected):
                raise BackupValidationError("backup file manifest and archive members differ")
            for relative, (expected_size, expected_hash) in expected.items():
                member = archive.getinfo(relative)
                digest = hashlib.sha256()
                size = 0
                with archive.open(member) as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        size += len(block)
                        digest.update(block)
                if size != expected_size:
                    raise BackupValidationError(f"backup file size mismatch: {relative}")
                if digest.hexdigest() != expected_hash:
                    raise BackupValidationError(f"backup file sha256 mismatch: {relative}")
    except KeyError as exc:
        raise BackupValidationError("backup file manifest references a missing archive member") from exc
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
    if not isinstance(manifest, dict) or manifest.get("format") not in {
        "careercrew-backup-v1",
        "careercrew-backup-v2",
    }:
        raise BackupValidationError("backup manifest format is invalid")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise BackupValidationError("backup manifest has no artifacts")
    qdrant_entries = manifest.get("qdrant", [])
    if not isinstance(qdrant_entries, list):
        raise BackupValidationError("backup Qdrant manifest is invalid")
    seen: set[str] = set()
    qdrant_artifact_paths: set[str] = set()
    files_artifact: Path | None = None
    postgres_artifact: Path | None = None
    files_artifact_count = 0
    postgres_artifact_count = 0
    for item in artifacts:
        if not isinstance(item, dict):
            raise BackupValidationError("backup artifact entry is invalid")
        relative = item.get("path")
        if not isinstance(relative, str):
            raise BackupValidationError("backup artifact path must be text")
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
            files_artifact_count += 1
        elif item.get("kind") == "postgres":
            postgres_artifact = path
            postgres_artifact_count += 1
        elif item.get("kind") == "qdrant_snapshot":
            qdrant_artifact_paths.add(relative)
    if (
        files_artifact is None
        or postgres_artifact is None
        or files_artifact_count != 1
        or postgres_artifact_count != 1
    ):
        raise BackupValidationError("backup must contain postgres and files artifacts")
    qdrant_manifest_paths: set[str] = set()
    for entry in qdrant_entries:
        if not isinstance(entry, dict):
            raise BackupValidationError("backup Qdrant entry is invalid")
        collection = entry.get("collection")
        relative = entry.get("path")
        snapshot = entry.get("snapshot")
        if not isinstance(collection, str) or not COLLECTION_RE.fullmatch(collection):
            raise BackupValidationError("backup Qdrant collection name is invalid")
        if not isinstance(relative, str) or relative in qdrant_manifest_paths:
            raise BackupValidationError("backup Qdrant artifact path is invalid or duplicated")
        if relative not in qdrant_artifact_paths:
            raise BackupValidationError("backup Qdrant entry has no hashed artifact")
        if not isinstance(snapshot, str) or not snapshot:
            raise BackupValidationError("backup Qdrant snapshot name is invalid")
        point_count = entry.get("point_count")
        if point_count is not None and (not isinstance(point_count, int) or point_count < 0):
            raise BackupValidationError("backup Qdrant point count is invalid")
        qdrant_manifest_paths.add(relative)
        _safe_backup_artifact(backup_dir, relative)
    if qdrant_manifest_paths != qdrant_artifact_paths:
        raise BackupValidationError("Qdrant manifest and hashed artifact sets differ")
    _validate_zip_members(files_artifact)
    if manifest.get("format") == "careercrew-backup-v2":
        _validate_file_manifest_archive(files_artifact, manifest)
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
    if runner is None and shutil.which("pg_restore") is None:
        # 主机没有 PostgreSQL 客户端时回退到容器内 pg_restore，从 stdin 读取 dump
        # （与 Qdrant 快照回退一致）。容器内走本地 socket，argv 不带密码。
        container = resolve_pg_container(os.getenv("CAREERCREW_PG_CONTAINER"))
        with dump_path.open("rb") as stream:
            process = subprocess.run(  # noqa: S603 -- argv is built from parsed non-secret fields
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "pg_restore",
                    "--exit-on-error",
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-privileges",
                    "--username",
                    config.user,
                    "--dbname",
                    target_database,
                ],
                cwd=ROOT,
                stdin=stream,
                capture_output=True,
                text=True,
                check=False,
            )
        if process.returncode != 0:
            raise BackupValidationError(
                f"pg_restore failed: {_compact_error(process.stderr or process.stdout or '')}"
            )
        return
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

        with psycopg.connect(normalize_dsn(database_url), autocommit=True) as connection:
            connection.execute(sql)
    except BackupValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - convert driver details to operator-safe error
        raise BackupValidationError(f"PostgreSQL administrative operation failed: {_compact_error(str(exc))}") from exc


def _validate_docker_target(value: str) -> str:
    target = value.strip() if isinstance(value, str) else ""
    if not target or not DOCKER_TARGET_RE.fullmatch(target):
        raise BackupValidationError("Qdrant container target is invalid")
    return target


def resolve_qdrant_container(explicit: str | None = None) -> str:
    """Resolve a running Qdrant container, preferring an explicit target."""

    requested = _validate_docker_target(explicit) if explicit and explicit.strip() else None
    if requested:
        try:
            inspect_process = subprocess.run(  # noqa: S603 -- explicit validated docker target
                ["docker", "inspect", "--format", "{{.Id}}|{{.State.Running}}", requested],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            inspect_process = None
        if inspect_process is not None and inspect_process.returncode == 0:
            inspected = inspect_process.stdout.strip().split("|", 1)
            if len(inspected) == 2 and inspected[0] and inspected[1].lower() == "true":
                return requested
        raise BackupValidationError("Qdrant container could not be resolved")

    try:
        compose_process = subprocess.run(  # noqa: S603 -- fixed docker compose argv
            ["docker", "compose", "ps", "-q", "qdrant"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        compose_process = None
    if compose_process is not None and compose_process.returncode == 0:
        compose_target = next((line.strip() for line in compose_process.stdout.splitlines() if line.strip()), "")
        if compose_target:
            return _validate_docker_target(compose_target)

    try:
        legacy_process = subprocess.run(  # noqa: S603 -- fixed exact-name compatibility fallback
            ["docker", "ps", "--filter", "name=^qdrant$", "--format", "{{.ID}}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        legacy_process = None
    if legacy_process is not None and legacy_process.returncode == 0:
        legacy_target = next((line.strip() for line in legacy_process.stdout.splitlines() if line.strip()), "")
        if legacy_target:
            return _validate_docker_target(legacy_target)
    raise BackupValidationError("Qdrant container could not be resolved")


def resolve_pg_container(explicit: str | None = None) -> str:
    """Resolve a running PostgreSQL container for hosts without client binaries."""

    requested = _validate_docker_target(explicit) if explicit and explicit.strip() else None
    if requested:
        try:
            inspect_process = subprocess.run(  # noqa: S603 -- explicit validated docker target
                ["docker", "inspect", "--format", "{{.Id}}|{{.State.Running}}", requested],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            inspect_process = None
        if inspect_process is not None and inspect_process.returncode == 0:
            inspected = inspect_process.stdout.strip().split("|", 1)
            if len(inspected) == 2 and inspected[0] and inspected[1].lower() == "true":
                return requested
        raise BackupValidationError("PostgreSQL container could not be resolved")

    try:
        compose_process = subprocess.run(  # noqa: S603 -- fixed docker compose argv
            ["docker", "compose", "ps", "-q", "postgres"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        compose_process = None
    if compose_process is not None and compose_process.returncode == 0:
        compose_target = next(
            (line.strip() for line in compose_process.stdout.splitlines() if line.strip()), ""
        )
        if compose_target:
            return _validate_docker_target(compose_target)

    try:
        legacy_process = subprocess.run(  # noqa: S603 -- fixed exact-name compatibility fallback
            ["docker", "ps", "--filter", "name=^postgres$", "--format", "{{.ID}}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        legacy_process = None
    if legacy_process is not None and legacy_process.returncode == 0:
        legacy_target = next(
            (line.strip() for line in legacy_process.stdout.splitlines() if line.strip()), ""
        )
        if legacy_target:
            return _validate_docker_target(legacy_target)
    raise BackupValidationError("PostgreSQL container could not be resolved")


@contextmanager
def _extract_files_to_temp(files_path: Path):
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
        yield target


def _verify_restored_file_manifest(extracted_root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Verify that the restore target contains exactly the backed-up files."""

    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise BackupValidationError("restore requires a per-file backup manifest")
    expected: dict[str, tuple[int, str]] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise BackupValidationError("restore file manifest entry is invalid")
        relative = item.get("path")
        size = item.get("size")
        sha256 = item.get("sha256")
        if (
            not isinstance(relative, str)
            or "\\" in relative
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(sha256, str)
            or not SHA256_RE.fullmatch(sha256)
            or relative in expected
        ):
            raise BackupValidationError("restore file manifest entry is invalid")
        expected[relative] = (size, sha256)

    actual_paths = {
        path.relative_to(extracted_root).as_posix()
        for path in extracted_root.rglob("*")
        if path.is_file()
    }
    if actual_paths != set(expected):
        raise BackupValidationError("restored files and backup manifest differ")
    for relative, (expected_size, expected_hash) in expected.items():
        path = _safe_backup_artifact(extracted_root, relative)
        actual_size, actual_hash = _artifact_digest(path)
        if actual_size != expected_size:
            raise BackupValidationError(f"restored file size mismatch: {relative}")
        if actual_hash != expected_hash:
            raise BackupValidationError(f"restored file sha256 mismatch: {relative}")
    return {
        "expected_files": len(expected),
        "verified_files": len(expected),
        "sha256_verified": True,
    }


def _verify_restored_postgres(target_url: str) -> None:
    """Run a connectivity canary and the current schema invariants on a restore target."""

    try:
        import psycopg

        from scripts.validate_migrations import validate_schema_invariants

        with psycopg.connect(normalize_dsn(target_url)) as connection:
            connection.execute("SELECT 1")
            validate_schema_invariants(connection)
    except BackupValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - convert driver/schema details to safe drill error
        raise BackupValidationError(
            f"restored PostgreSQL schema verification failed: {_compact_error(str(exc))}"
        ) from exc


def _fetch_canary_count(cursor: Any, query: str) -> int:
    cursor.execute(query)
    row = cursor.fetchone()
    try:
        value = int(row[0])
    except (TypeError, ValueError, IndexError, KeyError) as exc:
        raise BackupValidationError("restored PostgreSQL canary returned an invalid count") from exc
    if value < 0:
        raise BackupValidationError("restored PostgreSQL canary returned a negative count")
    return value


def _verify_restored_database_canary(target_url: str) -> dict[str, Any]:
    """Check representative rows and cross-table relationships on the restored DB."""

    table_queries = {
        "knowledge_documents": "SELECT COUNT(*) FROM knowledge_documents",
        "knowledge_document_versions": "SELECT COUNT(*) FROM knowledge_document_versions",
        "knowledge_document_chunks": "SELECT COUNT(*) FROM knowledge_document_chunks",
        "memory_records": "SELECT COUNT(*) FROM memory_records",
    }
    relationship_queries = {
        "knowledge_versions_without_document": (
            "SELECT COUNT(*) FROM knowledge_document_versions v "
            "LEFT JOIN knowledge_documents d ON d.id=v.document_id WHERE d.id IS NULL"
        ),
        "knowledge_chunks_without_version": (
            "SELECT COUNT(*) FROM knowledge_document_chunks c "
            "LEFT JOIN knowledge_document_versions v ON v.id=c.version_id WHERE v.id IS NULL"
        ),
        "knowledge_citations_without_chunk": (
            "SELECT COUNT(*) FROM knowledge_citation_events e "
            "LEFT JOIN knowledge_document_chunks c ON c.id=e.chunk_id WHERE c.id IS NULL"
        ),
        "knowledge_active_version_missing": (
            "SELECT COUNT(*) FROM knowledge_documents d "
            "LEFT JOIN knowledge_document_versions v ON v.id=d.active_version_id "
            "WHERE d.active_version_id IS NOT NULL AND v.id IS NULL"
        ),
        "memory_sources_without_record": (
            "SELECT COUNT(*) FROM memory_sources s "
            "LEFT JOIN memory_records r ON r.id=s.memory_id WHERE r.id IS NULL"
        ),
        "memory_relations_without_record": (
            "SELECT COUNT(*) FROM memory_relations mr "
            "LEFT JOIN memory_records source ON source.id=mr.from_memory_id "
            "LEFT JOIN memory_records target ON target.id=mr.to_memory_id "
            "WHERE source.id IS NULL OR target.id IS NULL"
        ),
    }
    try:
        import psycopg

        with psycopg.connect(normalize_dsn(target_url)) as connection:
            cursor = connection.cursor()
            tables = {
                name: _fetch_canary_count(cursor, query)
                for name, query in table_queries.items()
            }
            relationships = {
                name: _fetch_canary_count(cursor, query)
                for name, query in relationship_queries.items()
            }
    except BackupValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - convert driver/schema details to safe drill error
        raise BackupValidationError(
            f"restored PostgreSQL application canary failed: {_compact_error(str(exc))}"
        ) from exc
    violations = sum(relationships.values())
    if violations:
        raise BackupValidationError(
            f"restored PostgreSQL application relationships failed: {violations} orphan references"
        )
    return {
        "table_counts": tables,
        "relationship_violations": relationships,
        "canary_passed": True,
    }


def _verify_restored_application(
    target_url: str,
    extracted_root: Path,
    manifest: Mapping[str, Any],
    *,
    database_canary: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run both file-manifest and application relationship canaries."""

    files = _verify_restored_file_manifest(extracted_root, manifest)
    database = (database_canary or _verify_restored_database_canary)(target_url)
    if not isinstance(database, Mapping):
        raise BackupValidationError("restored PostgreSQL application canary returned invalid evidence")
    return {"files": files, "database": dict(database)}


def restore_qdrant_snapshots(
    backup_dir: Path,
    manifest: Mapping[str, Any],
    qdrant_url: str,
    qdrant_container: str | None,
    restore_stamp: str,
    *,
    qdrant_api_key: str | None = None,
) -> None:
    """Recover snapshots into temporary collections and remove them in finally.

    A local Docker container uses the file-backed recovery endpoint for
    backwards compatibility.  A remote/managed Qdrant uses the authenticated
    snapshot-upload endpoint instead, so a production restore drill does not
    depend on Docker being present on the operator workstation.
    """

    qdrant_entries = manifest.get("qdrant") or []
    if not isinstance(qdrant_entries, list):
        raise BackupValidationError("backup Qdrant manifest is invalid")
    container = (
        _validate_docker_target(qdrant_container)
        if qdrant_container and qdrant_container.strip()
        else None
    )
    base_url = qdrant_url.rstrip("/")
    headers = _qdrant_headers(qdrant_api_key, allow_environment=False)
    snapshot_directory = "/qdrant/snapshots"
    temporary: list[tuple[str, str]] = []
    copied_remote_names: list[str] = []
    cleanup_errors: list[str] = []
    try:
        if qdrant_entries and container:
            try:
                prepare_process = subprocess.run(  # noqa: S603 -- container/name are explicit operator inputs
                    ["docker", "exec", container, "mkdir", "-p", snapshot_directory],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise BackupValidationError("Qdrant snapshot directory preparation failed") from exc
            if prepare_process.returncode != 0:
                raise BackupValidationError("Qdrant snapshot directory preparation failed")
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
            encoded = quote(target_collection, safe="")
            # Register before recovery: a timeout or non-2xx response can
            # happen after Qdrant has already created the target collection.
            temporary.append((target_collection, remote_name))
            if container:
                copied_remote_names.append(remote_name)
                copy_process = subprocess.run(  # noqa: S603 -- container/name are explicit operator inputs
                    ["docker", "cp", str(snapshot_path), f"{container}:{snapshot_directory}/{remote_name}"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if copy_process.returncode != 0:
                    raise BackupValidationError("Qdrant snapshot copy to container failed")
                try:
                    response = requests.put(
                        f"{base_url}/collections/{encoded}/snapshots/recover",
                        headers=headers,
                        json={"location": f"file://{snapshot_directory}/{remote_name}"},
                        timeout=60,
                    )
                except requests.RequestException as exc:
                    raise BackupValidationError("Qdrant snapshot recovery request failed") from exc
            else:
                try:
                    with snapshot_path.open("rb") as snapshot:
                        response = requests.post(
                            f"{base_url}/collections/{encoded}/snapshots/upload?wait=true",
                            headers=headers,
                            files={
                                "snapshot": (
                                    snapshot_path.name,
                                    snapshot,
                                    "application/octet-stream",
                                )
                            },
                            timeout=120,
                        )
                except (OSError, requests.RequestException) as exc:
                    raise BackupValidationError("Qdrant snapshot upload failed") from exc
            _qdrant_json(response, f"snapshot recovery {collection}")
            try:
                info_response = requests.get(
                    f"{base_url}/collections/{encoded}", headers=headers, timeout=30,
                )
            except requests.RequestException as exc:
                raise BackupValidationError("Qdrant restored collection info request failed") from exc
            info = _qdrant_json(info_response, f"restored collection info {collection}")
            result = info.get("result")
            actual = result.get("points_count") if isinstance(result, dict) else None
            expected = entry.get("point_count")
            if expected is not None:
                try:
                    actual_count = int(actual)
                    expected_count = int(expected)
                except (TypeError, ValueError) as exc:
                    raise BackupValidationError(
                        f"Qdrant point count is invalid for {collection}"
                    ) from exc
                if actual_count != expected_count:
                    raise BackupValidationError(f"Qdrant point count mismatch for {collection}")
    finally:
        for collection, _remote_name in temporary:
            try:
                response = requests.delete(
                    f"{base_url}/collections/{quote(collection, safe='')}",
                    headers=headers,
                    timeout=30,
                )
                if response.status_code != 404:
                    response.raise_for_status()
            except requests.RequestException:
                cleanup_errors.append(f"collection {collection}")
        for remote_name in copied_remote_names:
            try:
                cleanup_process = subprocess.run(  # noqa: S603 -- cleanup uses the same validated operator inputs
                    [
                        "docker",
                        "exec",
                        container,
                        "rm",
                        "-f",
                        f"{snapshot_directory}/{remote_name}",
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                cleanup_errors.append(f"snapshot file {remote_name}: {_compact_error(str(exc))}")
                continue
            if cleanup_process.returncode != 0:
                detail = _compact_error(cleanup_process.stderr or cleanup_process.stdout or "")
                suffix = f": {detail}" if detail else ""
                cleanup_errors.append(f"snapshot file {remote_name}{suffix}")
        if cleanup_errors:
            raise BackupValidationError(
                "Qdrant restore cleanup failure: " + ", ".join(cleanup_errors)
            )


def restore_drill(
    backup_dir: Path | str,
    *,
    database_url: str,
    qdrant_url: str | None = None,
    qdrant_container: str | None = None,
    qdrant_api_key: str | None = None,
    now: datetime | None = None,
    application_canary: Callable[[str, Path, Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Restore into generated temporary targets and clean all targets in finally."""

    backup_dir = Path(backup_dir).expanduser().resolve()
    manifest = verify_backup(backup_dir)
    config = parse_database_url(database_url)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    restore_stamp = f"{timestamp.strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(8)}"
    target_database = f"careercrew_restore_{restore_stamp}"
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
    cleanup_required = True
    try:
        _execute_admin(admin_url, f'CREATE DATABASE "{target_database}"')
        restore_postgres_dump(dump_path, target_database, config)
        _verify_restored_postgres(target_url)
        with _extract_files_to_temp(files_path) as extracted_root:
            application_result = _verify_restored_application(
                target_url,
                extracted_root,
                manifest,
                database_canary=(
                    (lambda restored_url: application_canary(
                        restored_url, extracted_root, manifest,
                    ))
                    if application_canary is not None
                    else None
                ),
            )
            if manifest.get("qdrant"):
                requested_container = qdrant_container or ""
                resolved_container = (
                    resolve_qdrant_container(requested_container)
                    if requested_container.strip()
                    else None
                )
                restore_url = str(qdrant_url or "").strip()
                if not restore_url:
                    raise BackupValidationError("restore Qdrant URL is required")
                restore_qdrant_snapshots(
                    backup_dir,
                    manifest,
                    restore_url,
                    resolved_container,
                    restore_stamp,
                    qdrant_api_key=qdrant_api_key,
                )
        return {
            "temporary_database": target_database,
            "cleaned": True,
            "application_canary": application_result,
        }
    finally:
        if cleanup_required:
            try:
                _execute_admin(admin_url, f'DROP DATABASE IF EXISTS "{target_database}" WITH (FORCE)')
            except BackupValidationError as exc:
                raise BackupValidationError("restore drill cleanup failure") from exc


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
    drill_parser.add_argument("--database-url", default=os.getenv("RESTORE_DATABASE_URL", ""))
    drill_parser.add_argument("--qdrant-url", default=os.getenv("RESTORE_QDRANT_URL", ""))
    drill_parser.add_argument("--qdrant-container", default=os.getenv("RESTORE_QDRANT_CONTAINER"))

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
            result = restore_drill(
                args.backup_dir,
                database_url=args.database_url or "",
                qdrant_url=args.qdrant_url,
                qdrant_container=args.qdrant_container,
                qdrant_api_key=os.getenv("RESTORE_QDRANT_API_KEY"),
            )
            target = result.get("temporary_database") if isinstance(result, Mapping) else result
            print(f"restore drill: OK ({target} cleaned)")
    except BackupValidationError as exc:
        print(f"backup operation failed: {_compact_error(str(exc))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
