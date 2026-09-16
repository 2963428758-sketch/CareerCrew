"""Run the local release rehearsal gates for CareerCrew.

The command is deliberately read-mostly.  Migration validation, Qdrant
ownership verification, and backup verification are checks; the only
write-capable step is the restore drill, which is restricted to an isolated
PostgreSQL/Qdrant target and requires an explicit operator marker
(``CAREERCREW_RELEASE_RESTORE_DRILL=1``).

Only loopback endpoints are accepted: this runner rehearses a local Docker
deployment and reports ``rehearsal_passed``.  Production acceptance is out of
scope by decision (2026-09-16) because it would require a real production
target plus an independent evidence-verification service.
Passwords, API keys, prompts, answers, and subprocess output are not written
to the report.
"""
from __future__ import annotations

import argparse
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
    database_url: str = dataclass_field(repr=False)
    qdrant_url: str
    backup_dir: Path | None
    qdrant_container: str | None
    restore_approved: bool
    report_path: Path
    required_collections: tuple[str, ...] = DEFAULT_REQUIRED_COLLECTIONS
    qdrant_api_key: str | None = dataclass_field(default=None, repr=False)
    restore_database_url: str | None = dataclass_field(default=None, repr=False)
    restore_qdrant_url: str | None = None
    restore_qdrant_container: str | None = None
    restore_qdrant_api_key: str | None = dataclass_field(default=None, repr=False)


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


def resolve_config(
    *,
    database_url: str = "",
    qdrant_url: str = "",
    backup_dir: str | Path = "",
    qdrant_container: str = "",
    restore_database_url: str = "",
    restore_qdrant_url: str = "",
    restore_qdrant_container: str = "",
    restore_qdrant_api_key: str = "",
    report_path: str | Path = "",
    environ: Mapping[str, str] | None = None,
) -> AcceptanceConfig:
    """Resolve CLI/environment inputs for a loopback-only local rehearsal."""

    env = dict(os.environ if environ is None else environ)
    restore_approved = env.get("CAREERCREW_RELEASE_RESTORE_DRILL", "") == "1"

    source_database = str(database_url or env.get("DATABASE_URL", "")).strip()
    if source_database and not _is_loopback((_db_endpoint(source_database) or ("", 0))[0]):
        raise AcceptanceError("rehearsal 只允许回环数据库地址")

    source_qdrant = str(qdrant_url or env.get("QDRANT_URL", "")).strip() or DEFAULT_QDRANT_URL
    source_qdrant = _validate_qdrant_url(source_qdrant)
    if not _is_loopback(urlsplit(source_qdrant).hostname):
        raise AcceptanceError("rehearsal 只允许回环 Qdrant 地址")

    restore_database = str(restore_database_url or env.get("RESTORE_DATABASE_URL", "")).strip()
    if restore_database and not _is_loopback((_db_endpoint(restore_database) or ("", 0))[0]):
        raise AcceptanceError("rehearsal 只允许回环恢复数据库地址")

    restore_qdrant = str(restore_qdrant_url or env.get("RESTORE_QDRANT_URL", "")).strip()
    if restore_qdrant:
        restore_qdrant = _validate_qdrant_url(restore_qdrant, field="RESTORE_QDRANT_URL")
        if not _is_loopback(urlsplit(restore_qdrant).hostname):
            raise AcceptanceError("rehearsal 只允许回环恢复 Qdrant 地址")

    resolved_source_container = (qdrant_container or env.get("QDRANT_CONTAINER", "")).strip()
    resolved_restore_container = (
        restore_qdrant_container or env.get("RESTORE_QDRANT_CONTAINER", "")
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

    if restore_approved and (not restore_database or not restore_qdrant):
        raise AcceptanceError("恢复演练必须显式提供独立恢复目标")

    def _path(value: str | Path) -> Path | None:
        raw = str(value or "").strip()
        return Path(raw).expanduser().resolve() if raw else None

    report = _path(report_path)
    if report is None:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        report = ROOT / "data" / "reports" / f"release-acceptance-{stamp}.json"

    return AcceptanceConfig(
        database_url=source_database,
        qdrant_url=source_qdrant,
        backup_dir=_path(backup_dir),
        qdrant_container=resolved_source_container or None,
        restore_approved=restore_approved,
        report_path=report,
        required_collections=_collection_names(env),
        qdrant_api_key=str(env.get("QDRANT_API_KEY", "")).strip() or None,
        restore_database_url=restore_database or None,
        restore_qdrant_url=restore_qdrant or None,
        restore_qdrant_container=resolved_restore_container,
        restore_qdrant_api_key=resolved_restore_api_key,
    )


def _validate_acceptance_config(config: AcceptanceConfig) -> None:
    """Re-check the loopback-only boundary for direct callers of run_acceptance."""

    if config.database_url:
        endpoint = _db_endpoint(config.database_url)
        if not _is_loopback(endpoint[0]):
            raise AcceptanceError("rehearsal 只允许回环数据库地址")

    if config.qdrant_url:
        checked_qdrant = _validate_qdrant_url(config.qdrant_url)
        if not _is_loopback(urlsplit(checked_qdrant).hostname):
            raise AcceptanceError("rehearsal 只允许回环 Qdrant 地址")

    if config.restore_database_url:
        endpoint = _db_endpoint(config.restore_database_url)
        if not _is_loopback(endpoint[0]):
            raise AcceptanceError("rehearsal 只允许回环恢复数据库地址")

    if config.restore_qdrant_url:
        restore_qdrant = _validate_qdrant_url(
            config.restore_qdrant_url, field="RESTORE_QDRANT_URL"
        )
        if not _is_loopback(urlsplit(restore_qdrant).hostname):
            raise AcceptanceError("rehearsal 只允许回环恢复 Qdrant 地址")

    for field, value in (
        ("qdrant_container", config.qdrant_container),
        ("restore_qdrant_container", config.restore_qdrant_container),
    ):
        if value:
            try:
                backup_restore._validate_docker_target(value)
            except backup_restore.BackupValidationError as exc:
                raise AcceptanceError(f"{field} 不是合法 Docker 容器目标") from exc

    if config.restore_approved and (
        not config.restore_database_url or not config.restore_qdrant_url
    ):
        raise AcceptanceError("恢复演练必须显式提供隔离 PostgreSQL/Qdrant 目标")


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


@dataclass(frozen=True)
class AcceptanceAdapters:
    """Injectable boundaries keep the orchestration unit-testable."""

    migration_static: Callable[[], Any] = _default_migration_static
    migration_live: Callable[[str], Any] = _default_migration_live
    qdrant: Callable[[AcceptanceConfig], Any] = _default_qdrant
    ownership: Callable[[AcceptanceConfig], Any] = _default_ownership
    backup_verify: Callable[[Path], Any] = _default_backup_verify
    restore_drill: Callable[[AcceptanceConfig], Any] = _default_restore_drill



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


def _write_report(config: AcceptanceConfig, *, status: str, checks: list[dict[str, str]], started_at: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "format": "careercrew-release-acceptance-v1",
        "target": "local",
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

    prerequisite_names = {
        "migration_static", "migration_live", "qdrant_health", "qdrant_ownership", "backup_verify",
    }
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

    passed = all(item["status"] in {"passed", "not_applicable"} for item in checks)
    status = "rehearsal_passed" if passed else "failed"
    return _write_report(config, status=status, checks=checks, started_at=started_at)


    return _write_report(config, status=status, checks=checks, started_at=started_at)


def _load_environment() -> None:
    # A developer .env may contain loopback endpoints and credentials, which is
    # exactly what the local rehearsal needs.
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="", help="PostgreSQL DSN（默认取 DATABASE_URL）")
    parser.add_argument("--qdrant-url", default="", help="Qdrant 地址（默认取 QDRANT_URL 或本地默认值）")
    parser.add_argument("--backup-dir", default="", help="已生成并校验的 backup run 目录")
    parser.add_argument("--qdrant-container", default="", help="隔离恢复演练使用的 Qdrant 容器")
    parser.add_argument("--restore-database-url", default="", help="隔离恢复 PostgreSQL DSN")
    parser.add_argument("--restore-qdrant-url", default="", help="隔离恢复 Qdrant 地址")
    parser.add_argument("--restore-qdrant-container", default="", help="隔离恢复目标 Qdrant 容器")
    parser.add_argument("--report", default="", help="脱敏 JSON 报告路径")
    args = parser.parse_args(argv)
    _load_environment()
    report = Path(args.report).expanduser().resolve() if args.report else None
    try:
        config = resolve_config(
            database_url=args.database_url,
            qdrant_url=args.qdrant_url,
            backup_dir=args.backup_dir,
            qdrant_container=args.qdrant_container,
            restore_database_url=args.restore_database_url,
            restore_qdrant_url=args.restore_qdrant_url,
            restore_qdrant_container=args.restore_qdrant_container,
            report_path=report or "",
        )
    except AcceptanceError as exc:
        failure_path = report or ROOT / "data" / "reports" / "release-acceptance-config-failed.json"
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "careercrew-release-acceptance-v1",
            "target": "local",
            "status": "failed",
            "checks": [{"name": "config_guard", "status": "failed", "detail": redact_text(str(exc))}],
        }
        failure_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"release acceptance failed: {redact_text(str(exc))}; report={failure_path}", file=sys.stderr)
        return 2

    result = run_acceptance(config)
    print(f"release acceptance: {result['status']}; report={config.report_path}")
    return 0 if result["status"] == "rehearsal_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
