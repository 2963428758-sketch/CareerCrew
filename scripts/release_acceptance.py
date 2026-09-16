"""Run the protected release acceptance gates for CareerCrew.

The command is deliberately read-mostly.  Migration validation, Qdrant
ownership verification, and backup verification are checks; the only
write-capable step is the restore drill, which is restricted to an isolated
PostgreSQL/Qdrant target and requires an explicit operator marker.

Production mode is fail-closed: it needs ``CAREERCREW_RELEASE_TARGET=production``
and separate restore endpoints.  A local Docker rehearsal is reported as
``rehearsal_passed`` and is never represented as production acceptance.
Passwords, API keys, prompts, answers, and subprocess output are not written
to the report.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import backup_restore  # noqa: E402

DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_REQUIRED_COLLECTIONS = ("careercrew_mm", "careercrew_episodic_v2")
OPTIONAL_COLLECTIONS = frozenset({"careercrew_workspace_messages"})
TARGETS = frozenset({"local", "production"})
REMOTE_MEDIA_SCHEMES = frozenset({"az", "gs", "https", "s3"})
RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
DATABASE_PASSWORD_RE = re.compile(
    r"(postgres(?:ql)?(?:\+[^:\s/]+)?://[^:/@\s]+:)[^@\s]+(@)",
    re.IGNORECASE,
)
URL_PASSWORD_RE = re.compile(r"(://[^:/@\s]+:)[^@/\s]+(@)")
SECRET_VALUE_RE = re.compile(
    r"(?ix)"
    r"(?P<prefix>['\"]?(?:api[_-]?key|password|secret|token|authorization)['\"]?\s*[:=]\s*)"
    r"(?:"
    r"(?P<quote>['\"])(?P<quoted>.*?)(?P=quote)"
    r"|(?P<bearer>Bearer\s+\S+)"
    r"|(?P<bare>[^\s,;}\]]+)"
    r")"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AcceptanceError(RuntimeError):
    """A safe, operator-facing release acceptance failure."""


@dataclass(frozen=True)
class AcceptanceConfig:
    target: str
    database_url: str = dataclass_field(repr=False)
    qdrant_url: str
    backup_dir: Path | None
    backup_media_evidence: Path | None
    reindex_evidence: Path | None
    qdrant_container: str | None
    run_real_eval: bool
    restore_approved: bool
    report_path: Path
    required_collections: tuple[str, ...] = DEFAULT_REQUIRED_COLLECTIONS
    production_marker: str | None = None
    qdrant_api_key: str | None = dataclass_field(default=None, repr=False)
    restore_database_url: str | None = dataclass_field(default=None, repr=False)
    restore_qdrant_url: str | None = None
    restore_qdrant_container: str | None = None
    restore_qdrant_api_key: str | None = dataclass_field(default=None, repr=False)
    source_resource_id: str | None = None
    restore_resource_id: str | None = None
    evidence_verifier_url: str | None = None
    evidence_verifier_token: str | None = dataclass_field(default=None, repr=False)


def _redact_secret_match(match: re.Match[str]) -> str:
    quote = match.group("quote") or ""
    return f"{match.group('prefix')}{quote}***{quote}"


def redact_text(value: Any) -> str:
    """Return compact text with connection and secret-looking values removed."""

    text = str(value)
    text = DATABASE_PASSWORD_RE.sub(r"\1***\2", text)
    text = URL_PASSWORD_RE.sub(r"\1***\2", text)
    text = SECRET_VALUE_RE.sub(_redact_secret_match, text)
    return " ".join(text.split())[-500:]


def _is_loopback(host: str | None) -> bool:
    normalized = str(host or "").strip().lower().strip("[]").rstrip(".")
    if normalized == "localhost":
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(
        address.is_loopback
        or address.is_unspecified
        or address.is_link_local
        or (mapped is not None and mapped.is_loopback)
    )


def _validate_qdrant_url(value: str, *, field: str = "QDRANT_URL") -> str:
    url = str(value or "").strip()
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise AcceptanceError(f"{field} 无效") from exc
    if port is not None and not 1 <= port <= 65535:
        raise AcceptanceError(f"{field} 端口无效")
    if parsed.scheme not in {"http", "https"} or not host:
        raise AcceptanceError(f"{field} 必须是带主机的 HTTP(S) 地址")
    if parsed.username or parsed.password:
        raise AcceptanceError(f"{field} 不得在 URL 中携带凭据")
    return url.rstrip("/")


def _validate_evidence_verifier_url(value: str, *, target: str) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise AcceptanceError("CAREERCREW_RELEASE_EVIDENCE_VERIFIER_URL 无效") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or not parsed.netloc
    ):
        raise AcceptanceError(
            "CAREERCREW_RELEASE_EVIDENCE_VERIFIER_URL 必须是无凭据 HTTP(S) 地址"
        )
    if target == "production":
        if parsed.scheme != "https":
            raise AcceptanceError("生产 evidence verifier 必须使用 HTTPS")
        if _is_loopback(parsed.hostname):
            raise AcceptanceError("生产 evidence verifier 拒绝回环地址")
    return url.rstrip("/")


def _collection_names(environ: Mapping[str, str]) -> tuple[str, ...]:
    raw = environ.get("QDRANT_COLLECTIONS", "")
    names = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not names:
        names = DEFAULT_REQUIRED_COLLECTIONS
    required = tuple(name for name in names if name not in OPTIONAL_COLLECTIONS)
    return required or DEFAULT_REQUIRED_COLLECTIONS


def _db_endpoint(value: str) -> tuple[str, int] | None:
    try:
        config = backup_restore.parse_database_url(value)
    except backup_restore.BackupValidationError as exc:
        raise AcceptanceError(redact_text(str(exc))) from exc
    return config.host.lower().strip("[]"), config.port


def _resource_id(value: str | None, *, field: str) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if not RESOURCE_ID_RE.fullmatch(normalized):
        raise AcceptanceError(f"{field} 必须是安全的资源身份标识")
    return normalized


def resolve_config(
    *,
    target: str,
    database_url: str = "",
    qdrant_url: str = "",
    backup_dir: str | Path = "",
    backup_media_evidence: str | Path = "",
    reindex_evidence: str | Path = "",
    qdrant_container: str = "",
    restore_database_url: str = "",
    restore_qdrant_url: str = "",
    restore_qdrant_container: str = "",
    restore_qdrant_api_key: str = "",
    run_real_eval: bool = False,
    report_path: str | Path = "",
    environ: Mapping[str, str] | None = None,
) -> AcceptanceConfig:
    """Resolve CLI/environment inputs and enforce the production boundary."""

    env = dict(os.environ if environ is None else environ)
    normalized_target = str(target or "").strip().lower()
    if normalized_target not in TARGETS:
        raise AcceptanceError("target 必须是 local 或 production")
    production_marker = env.get("CAREERCREW_RELEASE_TARGET", "").strip().lower() or None
    restore_approved = env.get("CAREERCREW_RELEASE_RESTORE_DRILL", "") == "1"
    if normalized_target == "production" and production_marker != "production":
        raise AcceptanceError("生产验收必须设置 CAREERCREW_RELEASE_TARGET=production")
    if normalized_target == "production" and run_real_eval:
        try:
            from scripts.eval_runner import validate_runtime_eval_environment

            validate_runtime_eval_environment(env)
        except Exception as exc:
            if isinstance(exc, AcceptanceError):
                raise
            raise AcceptanceError("生产真实模型评测必须配置受保护 runtime 租户") from exc

    source_database = str(database_url or env.get("DATABASE_URL", "")).strip()
    if source_database:
        source_host, source_port = _db_endpoint(source_database) or ("", 0)
        if normalized_target == "production" and _is_loopback(source_host):
            raise AcceptanceError("生产数据库拒绝回环地址")
        if normalized_target == "local" and not _is_loopback(source_host):
            raise AcceptanceError("local 验收只允许回环数据库地址")
    else:
        source_host, source_port = "", 0

    if normalized_target == "production" and str(qdrant_url or "").strip():
        raise AcceptanceError("生产 Qdrant 地址必须从受保护环境变量 QDRANT_URL 注入")
    source_qdrant = str(qdrant_url or env.get("QDRANT_URL", "")).strip()
    if not source_qdrant and normalized_target == "local":
        source_qdrant = DEFAULT_QDRANT_URL
    if source_qdrant:
        source_qdrant = _validate_qdrant_url(source_qdrant)
        if normalized_target == "production" and _is_loopback(urlsplit(source_qdrant).hostname):
            raise AcceptanceError("生产 Qdrant 拒绝回环地址")
        if normalized_target == "local" and not _is_loopback(urlsplit(source_qdrant).hostname):
            raise AcceptanceError("local 验收只允许回环 Qdrant 地址")

    restore_database = str(restore_database_url or env.get("RESTORE_DATABASE_URL", "")).strip()
    if restore_database:
        restore_host, restore_port = _db_endpoint(restore_database) or ("", 0)
        if normalized_target == "production":
            if _is_loopback(restore_host):
                raise AcceptanceError("生产验收的隔离恢复数据库拒绝回环地址")
            if source_database and (restore_host, restore_port) == (source_host, source_port):
                raise AcceptanceError("生产恢复演练必须使用隔离恢复数据库端点")
        elif not _is_loopback(restore_host):
            raise AcceptanceError("local 验收只允许回环恢复数据库地址")

    restore_qdrant = str(restore_qdrant_url or env.get("RESTORE_QDRANT_URL", "")).strip()
    if restore_qdrant:
        restore_qdrant = _validate_qdrant_url(restore_qdrant, field="RESTORE_QDRANT_URL")
        if normalized_target == "production" and source_qdrant:
            source_parts = urlsplit(source_qdrant)
            restore_parts = urlsplit(restore_qdrant)
            if (
                restore_parts.scheme,
                restore_parts.hostname,
                restore_parts.port or (443 if restore_parts.scheme == "https" else 80),
            ) == (
                source_parts.scheme,
                source_parts.hostname,
                source_parts.port or (443 if source_parts.scheme == "https" else 80),
            ):
                raise AcceptanceError("生产恢复演练必须使用隔离恢复 Qdrant 端点")
        elif normalized_target == "local" and not _is_loopback(urlsplit(restore_qdrant).hostname):
            raise AcceptanceError("local 验收只允许回环恢复 Qdrant 地址")
    resolved_source_container = (qdrant_container or env.get("QDRANT_CONTAINER", "")).strip()
    resolved_restore_container = (
        restore_qdrant_container
        or env.get("RESTORE_QDRANT_CONTAINER", "")
    ).strip() or None
    resolved_restore_api_key = str(
        restore_qdrant_api_key or env.get("RESTORE_QDRANT_API_KEY", "")
    ).strip() or None
    for field, value in (
        ("qdrant_container", resolved_source_container),
        ("restore_qdrant_container", resolved_restore_container),
    ):
        if value:
            try:
                backup_restore._validate_docker_target(value)
            except backup_restore.BackupValidationError as exc:
                raise AcceptanceError(f"{field} 不是合法 Docker 容器目标") from exc
    source_resource_id = _resource_id(
        env.get("CAREERCREW_RELEASE_SOURCE_RESOURCE_ID"),
        field="CAREERCREW_RELEASE_SOURCE_RESOURCE_ID",
    )
    restore_resource_id = _resource_id(
        env.get("CAREERCREW_RELEASE_RESTORE_RESOURCE_ID"),
        field="CAREERCREW_RELEASE_RESTORE_RESOURCE_ID",
    )
    evidence_verifier_url = str(
        env.get("CAREERCREW_RELEASE_EVIDENCE_VERIFIER_URL", "")
    ).strip() or None
    if evidence_verifier_url:
        evidence_verifier_url = _validate_evidence_verifier_url(
            evidence_verifier_url,
            target=normalized_target,
        )
    evidence_verifier_token = str(
        env.get("CAREERCREW_RELEASE_EVIDENCE_VERIFIER_TOKEN", "")
    ).strip() or None
    if normalized_target == "production" and restore_approved:
        if not source_resource_id or not restore_resource_id:
            raise AcceptanceError(
                "生产恢复演练必须提供源/恢复资源身份 attestation"
            )
        if source_resource_id == restore_resource_id:
            raise AcceptanceError("生产恢复演练的源/恢复资源身份必须不同")
    if normalized_target == "local" and restore_approved and (
        not restore_database or not restore_qdrant
    ):
        raise AcceptanceError("local 恢复演练必须显式提供独立恢复目标")
    if (
        normalized_target == "production"
        and resolved_source_container
        and resolved_restore_container
        and resolved_source_container == resolved_restore_container
    ):
        raise AcceptanceError("生产恢复演练必须使用隔离恢复 Qdrant 容器")

    def _path(value: str | Path) -> Path | None:
        raw = str(value or "").strip()
        return Path(raw).expanduser().resolve() if raw else None

    report = _path(report_path)
    if report is None:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        report = ROOT / "data" / "reports" / f"release-acceptance-{stamp}.json"

    return AcceptanceConfig(
        target=normalized_target,
        database_url=source_database,
        qdrant_url=source_qdrant,
        backup_dir=_path(backup_dir),
        backup_media_evidence=_path(backup_media_evidence),
        reindex_evidence=_path(reindex_evidence),
        qdrant_container=(qdrant_container or env.get("QDRANT_CONTAINER", "")).strip() or None,
        run_real_eval=bool(run_real_eval),
        restore_approved=env.get("CAREERCREW_RELEASE_RESTORE_DRILL", "") == "1",
        report_path=report,
        required_collections=_collection_names(env),
        production_marker=production_marker,
        qdrant_api_key=str(env.get("QDRANT_API_KEY", "")).strip() or None,
        restore_database_url=restore_database or None,
        restore_qdrant_url=restore_qdrant or None,
        restore_qdrant_container=resolved_restore_container,
        restore_qdrant_api_key=resolved_restore_api_key,
        source_resource_id=source_resource_id,
        restore_resource_id=restore_resource_id,
        evidence_verifier_url=evidence_verifier_url,
        evidence_verifier_token=evidence_verifier_token,
    )


def _validate_acceptance_config(config: AcceptanceConfig) -> None:
    """Re-check the immutable target boundary for direct callers of run_acceptance."""

    if config.target not in TARGETS:
        raise AcceptanceError("target 必须是 local 或 production")
    if config.target == "production":
        if config.production_marker != "production":
            raise AcceptanceError("生产验收缺少受保护目标标记")
        if not config.database_url or not config.qdrant_url:
            raise AcceptanceError("生产验收必须配置源 PostgreSQL 和 Qdrant")
        if not config.evidence_verifier_url or not config.evidence_verifier_token:
            raise AcceptanceError(
                "生产验收必须配置外部 evidence verifier URL 和 token"
            )
        _validate_evidence_verifier_url(
            config.evidence_verifier_url,
            target="production",
        )

    source_db_endpoint: tuple[str, int] | None = None
    if config.database_url:
        source_db_endpoint = _db_endpoint(config.database_url)
        if config.target == "production" and _is_loopback(source_db_endpoint[0]):
            raise AcceptanceError("生产数据库拒绝回环地址")
        if config.target == "local" and not _is_loopback(source_db_endpoint[0]):
            raise AcceptanceError("local 验收只允许回环数据库地址")

    if config.qdrant_url:
        checked_qdrant = _validate_qdrant_url(config.qdrant_url)
        if config.target == "production" and _is_loopback(urlsplit(checked_qdrant).hostname):
            raise AcceptanceError("生产 Qdrant 拒绝回环地址")
        if config.target == "local" and not _is_loopback(urlsplit(checked_qdrant).hostname):
            raise AcceptanceError("local 验收只允许回环 Qdrant 地址")

    if config.restore_database_url:
        restore_endpoint = _db_endpoint(config.restore_database_url)
        if config.target == "production" and _is_loopback(restore_endpoint[0]):
            raise AcceptanceError("生产验收的隔离恢复数据库拒绝回环地址")
        if config.target == "local" and not _is_loopback(restore_endpoint[0]):
            raise AcceptanceError("local 验收只允许回环恢复数据库地址")
        if config.target == "production" and source_db_endpoint == restore_endpoint:
            raise AcceptanceError("生产恢复演练必须使用隔离恢复数据库端点")

    if config.restore_qdrant_url:
        restore_qdrant = _validate_qdrant_url(
            config.restore_qdrant_url, field="RESTORE_QDRANT_URL"
        )
        if config.target == "production" and config.qdrant_url:
            source_parts = urlsplit(config.qdrant_url)
            restore_parts = urlsplit(restore_qdrant)
            source_endpoint = (
                source_parts.scheme,
                source_parts.hostname,
                source_parts.port or (443 if source_parts.scheme == "https" else 80),
            )
            restore_endpoint = (
                restore_parts.scheme,
                restore_parts.hostname,
                restore_parts.port or (443 if restore_parts.scheme == "https" else 80),
            )
            if source_endpoint == restore_endpoint:
                raise AcceptanceError("生产恢复演练必须使用隔离恢复 Qdrant 端点")
        if config.target == "local" and not _is_loopback(urlsplit(restore_qdrant).hostname):
            raise AcceptanceError("local 验收只允许回环恢复 Qdrant 地址")

    for field, value in (
        ("qdrant_container", config.qdrant_container),
        ("restore_qdrant_container", config.restore_qdrant_container),
    ):
        if value:
            try:
                backup_restore._validate_docker_target(value)
            except backup_restore.BackupValidationError as exc:
                raise AcceptanceError(f"{field} 不是合法 Docker 容器目标") from exc

    if config.restore_approved:
        if not config.restore_database_url or not config.restore_qdrant_url:
            raise AcceptanceError("恢复演练必须显式提供隔离 PostgreSQL/Qdrant 目标")
        if config.target == "production":
            if not config.source_resource_id or not config.restore_resource_id:
                raise AcceptanceError("生产恢复演练必须提供源/恢复资源身份 attestation")
            if config.source_resource_id == config.restore_resource_id:
                raise AcceptanceError("生产恢复演练的源/恢复资源身份必须不同")
        for field, value in (
            ("source_resource_id", config.source_resource_id),
            ("restore_resource_id", config.restore_resource_id),
        ):
            _resource_id(value, field=field)


def _validate_evidence_file(path: Path, *, target: str, kind: str) -> dict[str, Any]:
    if not path.is_file():
        raise AcceptanceError(f"{kind} evidence 文件不存在")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"{kind} evidence 不是有效 JSON") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"{kind} evidence 必须是 JSON object")
    if value.get("target") != target:
        raise AcceptanceError(f"{kind} evidence target 不匹配（实际 {value.get('target')!r}，期望 {target!r}）")
    return value


def _evidence_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AcceptanceError(f"evidence 缺少 {field}")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AcceptanceError(f"evidence.{field} 不是有效 ISO-8601 时间") from exc
    if parsed.tzinfo is None:
        raise AcceptanceError(f"evidence.{field} 必须包含时区")
    return parsed.astimezone(UTC)


def validate_backup_media_evidence(
    path: Path, *, target: str, backup_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate operator evidence for encrypted/off-site/immutable media."""

    value = _validate_evidence_file(path, target=target, kind="backup media")
    if value.get("status") != "verified":
        raise AcceptanceError("backup media evidence status 必须为 verified")
    verified_at = _evidence_time(value.get("verified_at"), "verified_at")
    artifact_count = value.get("artifact_count")
    if isinstance(artifact_count, bool) or not isinstance(artifact_count, int) or artifact_count < 1:
        raise AcceptanceError("backup media evidence artifact_count 必须为正整数")
    for field in ("encrypted", "offsite", "immutable"):
        if value.get(field) is not True:
            raise AcceptanceError(f"backup media evidence.{field} 必须为 true")
    provider = str(value.get("provider") or "").strip().lower()
    if provider not in {"aws_s3", "azure_blob", "gcs", "https_object_store", "s3"}:
        raise AcceptanceError(
            "backup media evidence.provider 必须是受支持的对象存储提供方"
        )
    if value.get("provider_verified") is not True or value.get("remote_exists") is not True:
        raise AcceptanceError(
            "backup media evidence 必须包含 provider/object existence verification"
        )
    provider_verification_id = str(value.get("provider_verification_id") or "").strip()
    if not provider_verification_id or len(provider_verification_id) > 128:
        raise AcceptanceError("backup media evidence 缺少 provider_verification_id")
    manifest_sha256 = str(value.get("manifest_sha256") or "").strip().lower()
    if not SHA256_RE.fullmatch(manifest_sha256):
        raise AcceptanceError("backup media evidence.manifest_sha256 必须是 64 位 SHA-256")
    remote_manifest_sha256 = str(value.get("remote_manifest_sha256") or "").strip().lower()
    if not SHA256_RE.fullmatch(remote_manifest_sha256):
        raise AcceptanceError(
            "backup media evidence.remote_manifest_sha256 必须是 64 位 SHA-256"
        )
    if remote_manifest_sha256 != manifest_sha256:
        raise AcceptanceError(
            "backup media evidence.remote_manifest_sha256 与 manifest_sha256 不匹配"
        )
    media_uri = str(value.get("media_uri") or "").strip()
    try:
        parsed_uri = urlsplit(media_uri)
        media_host = parsed_uri.hostname
    except ValueError as exc:
        raise AcceptanceError("backup media evidence.media_uri 无效") from exc
    if (
        not media_uri
        or parsed_uri.scheme.lower() not in REMOTE_MEDIA_SCHEMES
        or not parsed_uri.netloc
        or not parsed_uri.path.strip("/")
        or _is_loopback(media_host)
    ):
        raise AcceptanceError("backup media evidence.media_uri 必须是远端介质 URI")
    verification_id = str(value.get("verification_id") or "").strip()
    if not verification_id or len(verification_id) > 128:
        raise AcceptanceError("backup media evidence 缺少 verification_id")
    retention_days = value.get("retention_days")
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 1:
        raise AcceptanceError("backup media evidence.retention_days 必须为正整数")
    immutable_until = _evidence_time(value.get("immutable_until"), "immutable_until")
    if immutable_until <= verified_at:
        raise AcceptanceError("backup media evidence immutable_until 必须晚于 verified_at")
    if backup_dir is not None:
        manifest_path = Path(backup_dir).expanduser().resolve() / "manifest.json"
        if not manifest_path.is_file():
            raise AcceptanceError("backup media evidence 绑定的 backup manifest 不存在")
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            actual_manifest_sha256 = _sha256_file(manifest_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise AcceptanceError("backup media evidence 绑定的 backup manifest 不可读") from exc
        if manifest_sha256 != actual_manifest_sha256:
            raise AcceptanceError("backup media evidence.manifest_sha256 与 backup manifest 不匹配")
        if remote_manifest_sha256 != actual_manifest_sha256:
            raise AcceptanceError(
                "backup media evidence.remote_manifest_sha256 与 backup manifest 不匹配"
            )
        artifacts = manifest_payload.get("artifacts") if isinstance(manifest_payload, dict) else None
        if not isinstance(artifacts, list) or len(artifacts) != artifact_count:
            raise AcceptanceError(
                "backup media evidence.artifact_count 与 backup manifest 不匹配"
            )
    return {
        "artifact_count": artifact_count,
        "provider": provider,
        "verified_at": verified_at.isoformat(),
        "retention_days": retention_days,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_reindex_evidence(path: Path, *, target: str) -> dict[str, Any]:
    """Validate reindex counts, canary, shadow cutover, and cleanup evidence."""

    value = _validate_evidence_file(path, target=target, kind="reindex")
    if value.get("status") != "completed":
        raise AcceptanceError("reindex evidence status 必须为 completed")
    started_at = _evidence_time(value.get("started_at"), "started_at")
    completed_at = _evidence_time(value.get("completed_at"), "completed_at")
    verified_at = _evidence_time(value.get("verified_at"), "verified_at")
    cutover_at = _evidence_time(value.get("cutover_at"), "cutover_at")
    cleanup_at = _evidence_time(value.get("cleanup_at"), "cleanup_at")
    if not started_at <= completed_at <= verified_at:
        raise AcceptanceError("reindex evidence 时间顺序无效")
    if cutover_at < completed_at or cleanup_at < cutover_at:
        raise AcceptanceError("reindex evidence cutover/cleanup 时间顺序无效")
    source_collection = str(value.get("source_collection") or "").strip()
    shadow_collection = str(value.get("shadow_collection") or "").strip()
    if not source_collection or not shadow_collection:
        raise AcceptanceError("reindex evidence 缺少 source_collection 或 shadow_collection")
    if source_collection == shadow_collection or not re.fullmatch(r"[A-Za-z0-9_.-]+", shadow_collection):
        raise AcceptanceError("reindex evidence.shadow_collection 必须是独立合法集合")
    for field in ("documents", "versions", "chunks", "failed", "owner_conflicts"):
        number = value.get(field)
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise AcceptanceError(f"reindex evidence.{field} 必须为非负整数")
    if value["documents"] < 1 or value["versions"] < 1 or value["chunks"] < 1:
        raise AcceptanceError("reindex evidence 必须证明至少有一份文档、版本和分块")
    if value.get("failed") != 0 or value.get("owner_conflicts") != 0:
        raise AcceptanceError("reindex evidence 存在失败或 owner 冲突")
    if value.get("cutover") != "completed":
        raise AcceptanceError("reindex evidence.cutover 必须为 completed")
    if value.get("canary_passed") is not True or value.get("cleanup_passed") is not True:
        raise AcceptanceError("reindex evidence 必须包含通过的 canary 和 cleanup")
    canary_queries = value.get("canary_queries")
    if isinstance(canary_queries, bool) or not isinstance(canary_queries, int) or canary_queries < 1:
        raise AcceptanceError("reindex evidence.canary_queries 必须为正整数")
    return {
        "documents": value["documents"],
        "versions": value["versions"],
        "chunks": value["chunks"],
        "source_collection": source_collection,
        "shadow_collection": shadow_collection,
        "canary_queries": canary_queries,
    }


def verify_protected_evidence(
    config: AcceptanceConfig,
    kind: str,
    path: Path,
) -> dict[str, Any]:
    """Ask an external authority to verify provider-side release evidence.

    The local JSON is treated as a pointer and digest source only.  Provider
    existence, immutability, remote manifest equality, and reindex/cutover
    facts must be attested by the protected verifier; none of those facts are
    accepted from a local boolean alone.
    """

    if config.target != "production":
        raise AcceptanceError("外部 evidence verifier 仅用于 production 验收")
    if not config.evidence_verifier_url or not config.evidence_verifier_token:
        raise AcceptanceError("生产验收缺少外部 evidence verifier")
    verifier_url = _validate_evidence_verifier_url(
        config.evidence_verifier_url,
        target="production",
    )
    value = _validate_evidence_file(path, target="production", kind=kind)
    evidence_sha256 = _sha256_file(path)
    from scripts.deployment_identity import deployment_identity

    try:
        deployments = {
            "source": deployment_identity(config.database_url, config.qdrant_url),
            "restore": deployment_identity(config.restore_database_url or "", config.restore_qdrant_url or ""),
        }
    except ValueError as exc:
        raise AcceptanceError("external deployment endpoints invalid") from exc
    payload: dict[str, Any] = {
        "contract": "careercrew-release-evidence-v1",
        "target": config.target,
        "kind": kind,
        "evidence_sha256": evidence_sha256,
        "manifest_sha256": value.get("manifest_sha256"),
        "verification_id": value.get("verification_id"),
        "source_resource_id": config.source_resource_id,
        "restore_resource_id": config.restore_resource_id,
        "deployments": deployments,
    }
    try:
        response = requests.post(
            verifier_url,
            headers={"Authorization": f"Bearer {config.evidence_verifier_token}"},
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        receipt = response.json()
    except (OSError, requests.RequestException, ValueError) as exc:
        raise AcceptanceError("外部 evidence verifier 请求失败") from exc
    if not isinstance(receipt, dict):
        raise AcceptanceError("外部 evidence verifier 回执格式无效")
    if receipt.get("deployments") != deployments:
        raise AcceptanceError("external deployment binding mismatch")
    if (
        receipt.get("status") != "verified"
        or receipt.get("target") != config.target
        or receipt.get("kind") != kind
        or receipt.get("evidence_sha256") != evidence_sha256
    ):
        raise AcceptanceError("外部 evidence verifier 回执与本次 evidence 不匹配")
    remote_id = str(receipt.get("remote_verification_id") or "").strip()
    if not remote_id or len(remote_id) > 128:
        raise AcceptanceError("外部 evidence verifier 缺少 remote_verification_id")
    if config.source_resource_id and receipt.get("source_resource_id") != config.source_resource_id:
        raise AcceptanceError("外部 evidence verifier 未确认源资源身份")
    if config.restore_resource_id and receipt.get("restore_resource_id") != config.restore_resource_id:
        raise AcceptanceError("外部 evidence verifier 未确认恢复资源身份")
    if kind == "backup_media":
        if receipt.get("manifest_sha256") != value.get("manifest_sha256"):
            raise AcceptanceError("外部 evidence verifier 未确认远端 manifest hash")
        if receipt.get("remote_exists") is not True or receipt.get("immutable") is not True:
            raise AcceptanceError("外部 evidence verifier 未确认备份介质事实")
    elif kind == "reindex":
        for field in ("cutover", "canary_passed", "cleanup_passed"):
            if receipt.get(field) not in ({"completed"} if field == "cutover" else {True}):
                raise AcceptanceError("外部 evidence verifier 未确认重索引事实")
    return {
        "remote_verification_id": remote_id,
        "evidence_sha256": evidence_sha256,
    }


def _default_migration_static() -> None:
    from scripts.validate_migrations import validate_static

    validate_static()


def _default_migration_live(database_url: str) -> None:
    if not database_url:
        raise AcceptanceError("DATABASE_URL 未配置")
    from scripts.validate_migrations import _validate_database

    _validate_database(database_url)


def _default_qdrant(config: AcceptanceConfig) -> dict[str, Any]:
    if not config.qdrant_url:
        raise AcceptanceError("QDRANT_URL 未配置")
    headers = {}
    api_key = str(config.qdrant_api_key or "").strip()
    if api_key:
        headers["api-key"] = api_key
    base = config.qdrant_url.rstrip("/")
    try:
        health = requests.get(f"{base}/healthz", headers=headers, timeout=15)
        health.raise_for_status()
        response = requests.get(f"{base}/collections", headers=headers, timeout=15)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise AcceptanceError("Qdrant 健康检查或集合清单读取失败") from exc
    rows = (payload.get("result") or {}).get("collections") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise AcceptanceError("Qdrant 集合清单格式无效")
    names = {str(row.get("name")) for row in rows if isinstance(row, dict) and row.get("name")}
    missing = [name for name in config.required_collections if name not in names]
    if missing:
        raise AcceptanceError(f"Qdrant 缺少必需集合: {', '.join(missing)}")
    optional_missing = sorted(name for name in OPTIONAL_COLLECTIONS if name not in names)
    return {"required_collections": sorted(config.required_collections), "optional_missing": optional_missing}


def _default_ownership(config: AcceptanceConfig) -> dict[str, Any]:
    """Run the existing owner verifier with only the target URL overridden."""

    with tempfile.TemporaryDirectory(prefix="careercrew-owner-acceptance-") as temp_dir:
        report_path = Path(temp_dir) / "owner.json"
        env = os.environ.copy()
        env["QDRANT_URL"] = config.qdrant_url
        if config.qdrant_api_key:
            env["QDRANT_API_KEY"] = config.qdrant_api_key
        else:
            env.pop("QDRANT_API_KEY", None)
        process = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_qdrant_ownership.py"), "--report", str(report_path)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            raise AcceptanceError("Qdrant owner dry-run 失败")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AcceptanceError("Qdrant owner dry-run 报告缺失或无效") from exc
    if report.get("mode") != "DRY-RUN":
        raise AcceptanceError("Qdrant owner 验收禁止 apply 模式")
    if not set(config.required_collections).issubset(report.get("collections") or {}):
        raise AcceptanceError("Qdrant owner 报告未覆盖全部必需集合")
    unowned = sum(int(item.get("unowned", 0)) for item in (report.get("collections") or {}).values())
    if any(int(report.get(field, 0)) != 0 for field in ("conflicts", "unresolved")) or unowned:
        raise AcceptanceError("Qdrant owner dry-run 仍有冲突、孤儿点或未解决点")
    return {"scanned": int(report.get("scanned", 0)), "collections": sorted((report.get("collections") or {}).keys())}


def _default_backup_verify(path: Path) -> dict[str, Any]:
    manifest = backup_restore.verify_backup(path)
    if manifest.get("format") != "careercrew-backup-v2" or not isinstance(
        manifest.get("files"), list
    ):
        raise AcceptanceError("backup 必须包含 v2 per-file manifest")
    required = set(DEFAULT_REQUIRED_COLLECTIONS)
    actual = {
        str(item.get("collection"))
        for item in (manifest.get("qdrant") or [])
        if isinstance(item, dict) and item.get("collection")
    }
    missing = sorted(required - actual)
    if missing:
        raise AcceptanceError(
            "backup 缺少必需 Qdrant snapshot: " + ", ".join(missing)
        )
    return {
        "qdrant_collections": sorted(actual),
        "artifact_count": len(manifest.get("artifacts") or []),
        "file_count": len(manifest["files"]),
    }


def _default_backup_media(
    path: Path, target: str, backup_dir: Path | None = None,
) -> dict[str, Any]:
    return validate_backup_media_evidence(path, target=target, backup_dir=backup_dir)


def _default_reindex(path: Path, target: str) -> dict[str, Any]:
    return validate_reindex_evidence(path, target=target)


def _default_restore_drill(config: AcceptanceConfig) -> dict[str, Any]:
    if not config.backup_dir:
        raise AcceptanceError("backup_dir 未配置")
    if not config.restore_database_url or not config.restore_qdrant_url:
        raise AcceptanceError("恢复演练缺少隔离 PostgreSQL/Qdrant 目标")
    restore_result = backup_restore.restore_drill(
        config.backup_dir,
        database_url=config.restore_database_url,
        qdrant_url=config.restore_qdrant_url,
        qdrant_container=config.restore_qdrant_container,
        qdrant_api_key=config.restore_qdrant_api_key,
    )
    if isinstance(restore_result, Mapping):
        return dict(restore_result)
    return {"temporary_database": restore_result, "cleaned": True}


def _default_real_eval(config: AcceptanceConfig, report_path: Path) -> None:
    try:
        from scripts.eval_runner import validate_runtime_eval_environment

        validate_runtime_eval_environment(os.environ)
    except Exception as exc:
        raise AcceptanceError("受保护真实模型评测缺少 runtime 标记或隔离租户") from exc
    env = os.environ.copy()
    env["DATABASE_URL"] = config.database_url
    env["QDRANT_URL"] = config.qdrant_url
    if config.qdrant_api_key:
        env["QDRANT_API_KEY"] = config.qdrant_api_key
    else:
        env.pop("QDRANT_API_KEY", None)
    # Product-runtime evaluation does not need remote trace retention.  Keep
    # PII and prompts inside the protected runner unless a separate trace
    # retention/delete proof is supplied by the operator.
    env["CAREERCREW_EVAL_DISABLE_REMOTE_TRACING"] = "1"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "eval_runner.py"),
        "--real",
        "--runtime",
        "--require-real",
        "--compare",
        str(ROOT / "data" / "eval" / "baseline.json"),
        "--fail-on-regression",
        "--report",
        str(report_path),
    ]
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise AcceptanceError("受保护真实模型评测失败")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError("真实模型评测报告缺失或无效") from exc
    if payload.get("status") != "completed":
        raise AcceptanceError("真实模型评测未完成，禁止作为通过证据")


@dataclass(frozen=True)
class AcceptanceAdapters:
    """Injectable boundaries keep the orchestration unit-testable."""

    migration_static: Callable[[], Any] = _default_migration_static
    migration_live: Callable[[str], Any] = _default_migration_live
    qdrant: Callable[[AcceptanceConfig], Any] = _default_qdrant
    ownership: Callable[[AcceptanceConfig], Any] = _default_ownership
    backup_verify: Callable[[Path], Any] = _default_backup_verify
    backup_media: Callable[[Path, str, Path | None], Any] = _default_backup_media
    reindex: Callable[[Path, str], Any] = _default_reindex
    evidence_verifier: Callable[[AcceptanceConfig, str, Path], Any] = verify_protected_evidence
    restore_drill: Callable[[AcceptanceConfig], Any] = _default_restore_drill
    real_eval: Callable[[AcceptanceConfig, Path], Any] = _default_real_eval


def _safe_detail(value: Any) -> str:
    if value is None:
        return "OK"
    if isinstance(value, (dict, list, tuple)):
        try:
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            value = type(value).__name__
    return redact_text(value)


def _run_check(name: str, callback: Callable[[], Any]) -> dict[str, str]:
    try:
        result = callback()
    except Exception as exc:  # noqa: BLE001 - each gate must produce safe evidence
        return {"name": name, "status": "failed", "detail": redact_text(f"{type(exc).__name__}: {exc}")}
    return {"name": name, "status": "passed", "detail": _safe_detail(result)}


def _not_run(name: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": "not_run", "detail": redact_text(detail)}


def _not_applicable(name: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": "not_applicable", "detail": redact_text(detail)}


def _write_report(config: AcceptanceConfig, *, status: str, checks: list[dict[str, str]], started_at: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "format": "careercrew-release-acceptance-v1",
        "target": config.target,
        "status": status,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "database": backup_restore.redacted_database_identifier(backup_restore.parse_database_url(config.database_url))
        if config.database_url
        else None,
        "qdrant_url": redact_text(config.qdrant_url) if config.qdrant_url else None,
        "checks": checks,
    }
    report_path = config.report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_name(f".{report_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, report_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return payload


def run_acceptance(config: AcceptanceConfig, *, adapters: AcceptanceAdapters | None = None) -> dict[str, Any]:
    """Run checks in a fixed order and write a redacted machine-readable report."""

    _validate_acceptance_config(config)
    adapters = adapters or AcceptanceAdapters()
    started_at = datetime.now(UTC).isoformat()
    checks: list[dict[str, str]] = []

    checks.append(_run_check("migration_static", adapters.migration_static))
    if config.database_url:
        checks.append(_run_check("migration_live", lambda: adapters.migration_live(config.database_url)))
    else:
        checks.append({"name": "migration_live", "status": "failed", "detail": "DATABASE_URL 未配置"})

    if config.qdrant_url:
        qdrant_check = _run_check("qdrant_health", lambda: adapters.qdrant(config))
        checks.append(qdrant_check)
    else:
        qdrant_check = {"name": "qdrant_health", "status": "failed", "detail": "QDRANT_URL 未配置"}
        checks.append(qdrant_check)

    if qdrant_check["status"] == "passed":
        checks.append(_run_check("qdrant_ownership", lambda: adapters.ownership(config)))
    else:
        checks.append(_not_run("qdrant_ownership", "Qdrant 健康检查未通过"))

    backup_ok = bool(config.backup_dir and config.backup_dir.is_dir())
    if backup_ok:
        backup_check = _run_check("backup_verify", lambda: adapters.backup_verify(config.backup_dir))
        backup_ok = backup_check["status"] == "passed"
    else:
        backup_check = {"name": "backup_verify", "status": "failed", "detail": "backup_dir 不存在"}
    checks.append(backup_check)

    if config.target == "production":
        if config.backup_media_evidence:
            def _verify_backup_media() -> Any:
                local_result = adapters.backup_media(
                    config.backup_media_evidence, config.target, config.backup_dir,
                )
                remote_result = adapters.evidence_verifier(
                    config, "backup_media", config.backup_media_evidence,
                )
                return {"local": local_result, "verifier": remote_result}

            checks.append(_run_check(
                "backup_media",
                _verify_backup_media,
            ))
        else:
            checks.append({"name": "backup_media", "status": "failed", "detail": "生产验收缺少 backup media evidence"})
        if config.reindex_evidence:
            def _verify_reindex() -> Any:
                local_result = adapters.reindex(config.reindex_evidence, config.target)
                remote_result = adapters.evidence_verifier(
                    config, "reindex", config.reindex_evidence,
                )
                return {"local": local_result, "verifier": remote_result}

            checks.append(_run_check(
                "reindex",
                _verify_reindex,
            ))
        else:
            checks.append({"name": "reindex", "status": "failed", "detail": "生产验收缺少 reindex evidence"})
    else:
        checks.append(_not_applicable("backup_media", "local 演练不等同于生产备份介质验收"))
        checks.append(_not_applicable("reindex", "local 演练不等同于生产重索引验收"))

    prerequisite_names = {
        "migration_static", "migration_live", "qdrant_health", "qdrant_ownership", "backup_verify",
    }
    if config.target == "production":
        prerequisite_names.update({"backup_media", "reindex"})
    prerequisites_ok = all(
        item["status"] == "passed"
        for item in checks
        if item["name"] in prerequisite_names
    )
    if not prerequisites_ok or not backup_ok or not config.database_url or not config.qdrant_url:
        checks.append(_not_run("restore_drill", "恢复演练前置条件未全部通过"))
    elif not config.restore_approved:
        checks.append(_not_run("restore_drill", "缺少 CAREERCREW_RELEASE_RESTORE_DRILL=1"))
    else:
        checks.append(_run_check("restore_drill", lambda: adapters.restore_drill(config)))

    core_ok = prerequisites_ok and checks[-1]["status"] == "passed"
    if config.run_real_eval and core_ok:
        eval_report = config.report_path.with_name(f"{config.report_path.stem}.real-eval.json")
        checks.append(_run_check("real_model_eval", lambda: adapters.real_eval(config, eval_report)))
    elif config.run_real_eval:
        checks.append(_not_run("real_model_eval", "迁移、Qdrant、备份或恢复前置检查未通过"))
    elif config.target == "production":
        checks.append(_not_run("real_model_eval", "生产验收必须显式指定 --run-real-eval"))
    else:
        checks.append(_not_applicable("real_model_eval", "local 演练不等同于受保护真实模型评测"))

    passed = all(item["status"] in {"passed", "not_applicable"} for item in checks)
    status = "accepted" if config.target == "production" and passed else (
        "rehearsal_passed" if config.target == "local" and passed else "failed"
    )
    return _write_report(config, status=status, checks=checks, started_at=started_at)


def _load_environment(*, target: str) -> None:
    # A developer .env may contain loopback endpoints and credentials.  It is
    # useful for local rehearsal, but production acceptance must use the
    # protected process environment explicitly.
    if target == "production":
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(TARGETS), default="local", help="验收目标；production 需要显式保护标记")
    parser.add_argument("--database-url", default="", help="PostgreSQL DSN；生产建议通过 DATABASE_URL 环境变量提供")
    parser.add_argument("--qdrant-url", default="", help="源 Qdrant HTTP(S) 地址；生产建议通过 QDRANT_URL 提供")
    parser.add_argument("--backup-dir", default="", help="已生成并校验的 backup run 目录")
    parser.add_argument("--backup-media-evidence", default="", help="备份介质 verified JSON（production 必填）")
    parser.add_argument("--reindex-evidence", default="", help="重索引/canary/cutover verified JSON（production 必填）")
    parser.add_argument("--qdrant-container", default="", help="隔离恢复演练使用的 Qdrant 容器")
    parser.add_argument("--restore-database-url", default="", help="隔离恢复 PostgreSQL DSN；production 必须与源端点分离")
    parser.add_argument("--restore-qdrant-url", default="", help="隔离恢复 Qdrant 地址；production 必须与源端点分离")
    parser.add_argument("--restore-qdrant-container", default="", help="隔离恢复目标 Qdrant 容器")
    parser.add_argument("--run-real-eval", action="store_true", help="运行 --real --require-real 受保护模型回归门禁")
    parser.add_argument("--report", default="", help="脱敏 JSON 报告路径")
    args = parser.parse_args(argv)
    _load_environment(target=args.target)
    report = Path(args.report).expanduser().resolve() if args.report else None
    try:
        if args.target == "production" and any(
            value.strip()
            for value in (args.database_url, args.restore_database_url)
            if isinstance(value, str)
        ):
            raise AcceptanceError("生产 PostgreSQL DSN 必须从受保护环境变量注入")
        config = resolve_config(
            target=args.target,
            database_url=args.database_url,
            qdrant_url=args.qdrant_url,
            backup_dir=args.backup_dir,
            backup_media_evidence=args.backup_media_evidence,
            reindex_evidence=args.reindex_evidence,
            qdrant_container=args.qdrant_container,
            restore_database_url=args.restore_database_url,
            restore_qdrant_url=args.restore_qdrant_url,
            restore_qdrant_container=args.restore_qdrant_container,
            run_real_eval=args.run_real_eval,
            report_path=report or "",
        )
    except AcceptanceError as exc:
        failure_path = report or ROOT / "data" / "reports" / "release-acceptance-target-failed.json"
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "careercrew-release-acceptance-v1",
            "target": args.target,
            "status": "failed",
            "checks": [{"name": "target_guard", "status": "failed", "detail": redact_text(str(exc))}],
        }
        failure_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"release acceptance failed: {redact_text(str(exc))}; report={failure_path}", file=sys.stderr)
        return 2

    result = run_acceptance(config)
    print(f"release acceptance: {result['status']}; report={config.report_path}")
    return 0 if result["status"] in {"accepted", "rehearsal_passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
