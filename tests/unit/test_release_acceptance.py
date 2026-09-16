"""Fail-closed tests for the protected release acceptance orchestrator."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.release_acceptance import (
    AcceptanceAdapters,
    AcceptanceConfig,
    AcceptanceError,
    _default_qdrant,
    _default_restore_drill,
    redact_text,
    resolve_config,
    run_acceptance,
    validate_backup_media_evidence,
    verify_protected_evidence,
)

PRODUCTION_DATABASE = "postgresql://release_user:super-secret@postgres.example:5432/careercrew"


def test_ownership_rejects_incomplete_collection_coverage(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from scripts import release_acceptance as acceptance

    def runner(command, **kwargs):
        report_path = Path(command[command.index("--report") + 1])
        report_path.write_text(json.dumps({"mode": "DRY-RUN", "scanned": 0,
                                          "collections": {"auxiliary": {"unowned": 0}}}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(acceptance.subprocess, "run", runner)
    with pytest.raises(AcceptanceError, match="集合"):
        acceptance._default_ownership(_production_config(tmp_path))


def _production_config(tmp_path: Path, *, run_real_eval: bool = True) -> AcceptanceConfig:
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    media = tmp_path / "backup-media.json"
    media.write_text("{}", encoding="utf-8")
    reindex = tmp_path / "reindex.json"
    reindex.write_text("{}", encoding="utf-8")
    return AcceptanceConfig(
        target="production",
        production_marker="production",
        database_url=PRODUCTION_DATABASE,
        qdrant_url="https://qdrant.example",
        qdrant_container="qdrant-prod",
        qdrant_api_key="source-qdrant-secret",
        restore_database_url="postgresql://restore_user:restore-secret@restore.example:5432/restore_control",
        restore_qdrant_url="https://qdrant-restore.example",
        restore_qdrant_container="qdrant-restore",
        restore_qdrant_api_key="restore-qdrant-secret",
        source_resource_id="prod/qdrant-cluster-a",
        restore_resource_id="restore/qdrant-cluster-b",
        evidence_verifier_url="https://release-verifier.example/v1/verify",
        evidence_verifier_token="verifier-secret",
        backup_dir=backup_dir,
        backup_media_evidence=media,
        reindex_evidence=reindex,
        run_real_eval=run_real_eval,
        restore_approved=True,
        report_path=tmp_path / "acceptance.json",
        required_collections=("careercrew_mm", "careercrew_episodic_v2"),
    )


def _successful_adapters(events: list[str]) -> AcceptanceAdapters:
    return AcceptanceAdapters(
        migration_static=lambda: events.append("migration_static"),
        migration_live=lambda _database_url: events.append("migration_live"),
        qdrant=lambda _config: events.append("qdrant") or {"collections": ["careercrew_mm", "careercrew_episodic_v2"]},
        ownership=lambda _config: events.append("ownership") or {"unowned": 0, "conflicts": 0},
        backup_verify=lambda _path: events.append("backup_verify"),
        backup_media=lambda _path, _target, _backup: events.append("backup_media"),
        reindex=lambda _path, _target: events.append("reindex"),
        evidence_verifier=lambda _config, _kind, _path: events.append("evidence_verifier"),
        restore_drill=lambda _config: events.append("restore_drill"),
        real_eval=lambda _config, _path: events.append("real_eval"),
    )


def test_production_target_requires_marker_and_rejects_loopback() -> None:
    with pytest.raises(AcceptanceError, match="CAREERCREW_RELEASE_TARGET"):
        resolve_config(
            target="production",
            database_url=PRODUCTION_DATABASE,
            qdrant_url="",
            environ={},
        )

    with pytest.raises(AcceptanceError, match="回环地址"):
        resolve_config(
            target="production",
            database_url="postgresql://release_user:secret@127.0.0.1:5432/careercrew",
            qdrant_url="",
            environ={
                "CAREERCREW_RELEASE_TARGET": "production",
                "QDRANT_URL": "https://qdrant.example",
            },
        )

    with pytest.raises(AcceptanceError, match="隔离恢复"):
        resolve_config(
            target="production",
            database_url=PRODUCTION_DATABASE,
            qdrant_url="",
            restore_database_url=PRODUCTION_DATABASE,
            environ={
                "CAREERCREW_RELEASE_TARGET": "production",
                "QDRANT_URL": "https://qdrant.example",
            },
        )


def test_local_target_rejects_remote_source_endpoints() -> None:
    with pytest.raises(AcceptanceError, match="local.*回环"):
        resolve_config(
            target="local",
            database_url="postgresql://user:secret@prod.example:5432/careercrew",
            qdrant_url="http://qdrant.example:6333",
            environ={},
        )


def test_local_restore_requires_explicit_isolated_targets() -> None:
    with pytest.raises(AcceptanceError, match="显式.*恢复"):
        resolve_config(
            target="local",
            database_url="postgresql://user:secret@localhost:5432/careercrew",
            qdrant_url="http://localhost:6333",
            environ={"CAREERCREW_RELEASE_RESTORE_DRILL": "1"},
        )


def test_production_qdrant_endpoint_must_come_from_protected_environment() -> None:
    with pytest.raises(AcceptanceError, match="生产 Qdrant 地址"):
        resolve_config(
            target="production",
            database_url=PRODUCTION_DATABASE,
            qdrant_url="https://qdrant.example",
            environ={
                "CAREERCREW_RELEASE_TARGET": "production",
                "QDRANT_URL": "https://protected-qdrant.example",
            },
        )


def test_production_restore_requires_resource_identity_attestation() -> None:
    with pytest.raises(AcceptanceError, match="资源身份"):
        resolve_config(
            target="production",
            database_url=PRODUCTION_DATABASE,
            restore_database_url="postgresql://restore_user:secret@restore.example:5432/restore_control",
            restore_qdrant_url="https://qdrant-restore.example",
            environ={
                "CAREERCREW_RELEASE_TARGET": "production",
                "QDRANT_URL": "https://qdrant.example",
                "CAREERCREW_RELEASE_RESTORE_DRILL": "1",
            },
        )


def test_run_acceptance_rejects_direct_unresolved_production_config(tmp_path: Path) -> None:
    config = AcceptanceConfig(
        target="production",
        database_url=PRODUCTION_DATABASE,
        qdrant_url="https://qdrant.example",
        backup_dir=None,
        backup_media_evidence=None,
        reindex_evidence=None,
        qdrant_container=None,
        run_real_eval=False,
        restore_approved=True,
        restore_database_url="postgresql://restore_user:secret@restore.example:5432/restore_control",
        restore_qdrant_url="https://qdrant-restore.example",
        report_path=tmp_path / "acceptance.json",
    )

    with pytest.raises(AcceptanceError, match="受保护目标标记"):
        run_acceptance(config, adapters=AcceptanceAdapters())


def test_production_acceptance_requires_external_evidence_verifier(tmp_path: Path) -> None:
    config = replace(
        _production_config(tmp_path, run_real_eval=False),
        evidence_verifier_url=None,
        evidence_verifier_token=None,
    )

    with pytest.raises(AcceptanceError, match="evidence verifier"):
        run_acceptance(config, adapters=AcceptanceAdapters())


def test_protected_evidence_requires_matching_remote_authority_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_path = tmp_path / "media.json"
    evidence_path.write_text(json.dumps({
        "status": "verified",
        "target": "production",
        "manifest_sha256": "a" * 64,
        "verification_id": "local-check",
    }), encoding="utf-8")
    requests_seen: list[dict[str, object]] = []
    bindings = {
        "source": {"database": {"host": "postgres.example", "port": 5432, "database": "careercrew"}, "qdrant": "https://qdrant.example:443"},
        "restore": {"database": {"host": "restore.example", "port": 5432, "database": "restore_control"}, "qdrant": "https://qdrant-restore.example:443"},
    }

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "status": "verified",
                "target": "production",
                    "kind": "backup_media",
                    "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                    "manifest_sha256": "a" * 64,
                    "remote_exists": True,
                    "immutable": True,
                    "remote_verification_id": "provider-side-check",
                    "source_resource_id": "prod/qdrant-cluster-a",
                    "restore_resource_id": "restore/qdrant-cluster-b",
                    "deployments": bindings,
                }

    import scripts.release_acceptance as acceptance

    def fake_post(url: str, **kwargs):
        requests_seen.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(acceptance.requests, "post", fake_post)
    config = _production_config(tmp_path)
    result = verify_protected_evidence(config, "backup_media", evidence_path)
    with pytest.raises(AcceptanceError, match="deployment"):
        verify_protected_evidence(replace(config, restore_qdrant_url="https://production-alias.example"), "backup_media", evidence_path)

    assert result["remote_verification_id"] == "provider-side-check"
    assert requests_seen[0]["url"] == "https://release-verifier.example/v1/verify"
    assert requests_seen[0]["headers"] == {"Authorization": "Bearer verifier-secret"}
    payload = requests_seen[0]["json"]
    assert isinstance(payload, dict)
    assert payload["evidence_sha256"] == hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    assert payload["deployments"] == bindings
    assert "verifier-secret" not in json.dumps(payload)


def test_qdrant_health_uses_configured_source_key(monkeypatch) -> None:
    calls: list[dict] = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": {"collections": [
                {"name": "careercrew_mm"}, {"name": "careercrew_episodic_v2"},
            ]}}

    def fake_get(_url, **kwargs):
        calls.append(kwargs)
        return Response()

    import scripts.release_acceptance as acceptance

    monkeypatch.setattr(acceptance.requests, "get", fake_get)
    monkeypatch.setenv("QDRANT_API_KEY", "wrong-environment-key")
    config = AcceptanceConfig(
        target="production",
        production_marker="production",
        database_url=PRODUCTION_DATABASE,
        qdrant_url="https://qdrant.example",
        qdrant_api_key="configured-source-key",
        backup_dir=None,
        backup_media_evidence=None,
        reindex_evidence=None,
        qdrant_container=None,
        run_real_eval=False,
        restore_approved=False,
        report_path=Path("acceptance.json"),
    )

    _default_qdrant(config)

    assert calls and all(call["headers"] == {"api-key": "configured-source-key"} for call in calls)


@pytest.mark.parametrize(
    "qdrant_url",
    ["https://127.0.0.2", "https://0.0.0.0", "https://[::1]"],
)
def test_production_target_rejects_non_routable_qdrant_addresses(qdrant_url: str) -> None:
    with pytest.raises(AcceptanceError, match="回环地址"):
        resolve_config(
            target="production",
            database_url=PRODUCTION_DATABASE,
            qdrant_url="",
            environ={
                "CAREERCREW_RELEASE_TARGET": "production",
                "QDRANT_URL": qdrant_url,
            },
        )


def test_qdrant_url_rejects_invalid_port() -> None:
    with pytest.raises(AcceptanceError, match="QDRANT_URL"):
        resolve_config(
            target="production",
            database_url=PRODUCTION_DATABASE,
            qdrant_url="",
            environ={
                "CAREERCREW_RELEASE_TARGET": "production",
                "QDRANT_URL": "https://qdrant.example:not-a-port",
            },
        )


def test_resolve_config_reads_restore_qdrant_key_only_from_environment() -> None:
    config = resolve_config(
        target="production",
        database_url=PRODUCTION_DATABASE,
        qdrant_url="",
        restore_database_url="postgresql://restore_user:restore-secret@restore.example:5432/restore_control",
        restore_qdrant_url="https://qdrant-restore.example",
        environ={
            "CAREERCREW_RELEASE_TARGET": "production",
            "QDRANT_URL": "https://qdrant.example",
            "RESTORE_QDRANT_API_KEY": "restore-qdrant-secret",
        },
    )

    assert config.restore_qdrant_api_key == "restore-qdrant-secret"
    assert "restore-qdrant-secret" not in repr(config)


def test_restore_adapter_supports_managed_qdrant_without_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup_dir = tmp_path / "careercrew-20260911-010000"
    backup_dir.mkdir()
    calls: dict[str, object] = {}

    def fake_restore(*args, **kwargs):
        calls["args"] = args
        calls.update(kwargs)
        return "careercrew_restore_20260911010000_test"

    import scripts.release_acceptance as acceptance

    monkeypatch.setattr(acceptance.backup_restore, "restore_drill", fake_restore)
    config = AcceptanceConfig(
        target="production",
        database_url=PRODUCTION_DATABASE,
        qdrant_url="https://qdrant.example",
        backup_dir=backup_dir,
        backup_media_evidence=None,
        reindex_evidence=None,
        qdrant_container=None,
        restore_database_url="postgresql://restore_user:restore-secret@restore.example:5432/restore_control",
        restore_qdrant_url="https://qdrant-restore.example",
        restore_qdrant_container=None,
        restore_qdrant_api_key="restore-qdrant-secret",
        run_real_eval=False,
        restore_approved=True,
        report_path=tmp_path / "acceptance.json",
    )

    assert _default_restore_drill(config)["cleaned"] is True
    assert calls["qdrant_container"] is None
    assert calls["qdrant_api_key"] == "restore-qdrant-secret"


def test_production_cli_does_not_load_dotenv_or_accept_dsn_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.release_acceptance as acceptance

    loaded_targets: list[str] = []
    monkeypatch.setattr(
        acceptance, "_load_environment", lambda *, target: loaded_targets.append(target),
    )
    monkeypatch.setenv("CAREERCREW_RELEASE_TARGET", "production")
    report = tmp_path / "target-guard.json"

    assert acceptance.main([
        "--target", "production",
        "--database-url", PRODUCTION_DATABASE,
        "--report", str(report),
    ]) == 2
    assert loaded_targets == ["production"]
    assert "生产 PostgreSQL DSN" in report.read_text(encoding="utf-8")


def test_local_restore_drill_requires_explicit_operator_marker(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    events: list[str] = []
    config = AcceptanceConfig(
        target="local",
        database_url="postgresql://user:secret@localhost:5432/careercrew",
        qdrant_url="http://localhost:6333",
        backup_dir=backup_dir,
        backup_media_evidence=None,
        reindex_evidence=None,
        qdrant_container=None,
        restore_database_url="postgresql://user:secret@localhost:5432/careercrew_restore_control",
        restore_qdrant_url="http://localhost:6333",
        restore_approved=False,
        run_real_eval=False,
        report_path=tmp_path / "local-acceptance.json",
    )

    adapters = AcceptanceAdapters(
        migration_static=lambda: None,
        migration_live=lambda _dsn: None,
        qdrant=lambda _config: None,
        ownership=lambda _config: None,
        backup_verify=lambda _path: None,
        restore_drill=lambda _config: events.append("restore"),
    )
    result = run_acceptance(config, adapters=adapters)

    assert result["status"] == "failed"
    assert events == []
    assert next(check for check in result["checks"] if check["name"] == "restore_drill")["status"] == "not_run"


def test_acceptance_runs_production_checks_in_order_and_redacts_report(tmp_path: Path) -> None:
    events: list[str] = []
    result = run_acceptance(_production_config(tmp_path), adapters=_successful_adapters(events))

    assert result["status"] == "accepted"
    assert events == [
        "migration_static",
        "migration_live",
        "qdrant",
        "ownership",
        "backup_verify",
        "backup_media",
        "evidence_verifier",
        "reindex",
        "evidence_verifier",
        "restore_drill",
        "real_eval",
    ]
    report_text = (tmp_path / "acceptance.json").read_text(encoding="utf-8")
    assert "super-secret" not in report_text
    assert "restore-secret" not in report_text
    assert "release_user@postgres.example:5432/careercrew" in report_text


def test_production_missing_backup_and_real_eval_fail_closed(tmp_path: Path) -> None:
    config = _production_config(tmp_path, run_real_eval=False)
    config = AcceptanceConfig(
        **{
            **config.__dict__,
            "backup_dir": tmp_path / "missing-backup",
            "backup_media_evidence": None,
            "reindex_evidence": None,
            "restore_approved": False,
        }
    )
    result = run_acceptance(config, adapters=_successful_adapters([]))

    assert result["status"] == "failed"
    statuses = {check["name"]: check["status"] for check in result["checks"]}
    assert statuses["backup_verify"] == "failed"
    assert statuses["backup_media"] == "failed"
    assert statuses["reindex"] == "failed"
    assert statuses["restore_drill"] == "not_run"
    assert statuses["real_model_eval"] == "not_run"


def test_redact_text_removes_dsn_passwords_and_secret_values() -> None:
    value = "connect postgresql://user:very-secret@db.example:5432/app api_key=sk-live-value"
    redacted = redact_text(value)

    assert "very-secret" not in redacted
    assert "sk-live-value" not in redacted
    assert "***" in redacted


def test_redact_text_removes_quoted_header_secrets() -> None:
    value = "headers={'api-key': 'quoted-secret', 'Authorization': 'Bearer token-value'}"
    redacted = redact_text(value)

    assert "quoted-secret" not in redacted
    assert "Bearer token-value" not in redacted


def test_redact_text_removes_unquoted_bearer_and_whitespace_secret_values() -> None:
    value = "Authorization: Bearer abc.def.ghi api_key='secret with spaces'"
    redacted = redact_text(value)

    assert "abc.def.ghi" not in redacted
    assert "secret with spaces" not in redacted


def test_production_evidence_is_machine_readable_and_target_bound(tmp_path: Path) -> None:
    config = _production_config(tmp_path)
    media = tmp_path / "media.json"
    media.write_text(json.dumps({
        "status": "verified",
        "target": "production",
        "verified_at": "2026-09-11T01:00:00Z",
        "artifact_count": 3,
        "media": "object-storage://release/backup",
        "media_uri": "s3://release/backup/20260911",
        "manifest_sha256": "a" * 64,
        "verification_id": "media-check-20260911",
        "retention_days": 30,
        "immutable_until": "2026-10-11T01:00:00Z",
        "encrypted": True,
        "offsite": True,
        "immutable": True,
        "provider": "s3",
        "provider_verified": True,
        "remote_exists": True,
        "provider_verification_id": "aws-check-20260911",
        "remote_manifest_sha256": "a" * 64,
    }), encoding="utf-8")
    reindex = tmp_path / "reindex.json"
    reindex.write_text(json.dumps({
        "status": "completed",
        "target": "production",
        "started_at": "2026-09-11T00:00:00Z",
        "completed_at": "2026-09-11T00:20:00Z",
        "verified_at": "2026-09-11T00:21:00Z",
        "cutover_at": "2026-09-11T00:20:30Z",
        "cleanup_at": "2026-09-11T00:21:00Z",
        "documents": 2,
        "versions": 2,
        "chunks": 18,
        "failed": 0,
        "owner_conflicts": 0,
        "source_collection": "careercrew_mm",
        "shadow_collection": "careercrew_mm__release_20260911",
        "canary_queries": 3,
        "cutover": "completed",
        "canary_passed": True,
        "cleanup_passed": True,
    }), encoding="utf-8")
    result = run_acceptance(
        AcceptanceConfig(
            **{
                **config.__dict__,
                "backup_media_evidence": media,
                "reindex_evidence": reindex,
            }
        ),
        adapters=AcceptanceAdapters(
            migration_static=lambda: None,
            migration_live=lambda _database_url: None,
            qdrant=lambda _config: None,
            ownership=lambda _config: None,
                backup_verify=lambda _path: None,
                backup_media=lambda _path, _target, _backup: None,
                reindex=lambda _path, _target: None,
                evidence_verifier=lambda _config, _kind, _path: None,
                restore_drill=lambda _config: None,
            real_eval=lambda _config, _path: None,
        ),
    )

    assert result["status"] == "accepted"
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["backup_media"]["status"] == "passed"
    assert checks["reindex"]["status"] == "passed"


def test_restore_drill_is_not_run_when_production_prerequisite_fails(tmp_path: Path) -> None:
    events: list[str] = []
    result = run_acceptance(
        _production_config(tmp_path, run_real_eval=False),
        adapters=AcceptanceAdapters(
            migration_static=lambda: None,
            migration_live=lambda _database_url: None,
            qdrant=lambda _config: None,
            ownership=lambda _config: None,
            backup_verify=lambda _path: None,
            backup_media=lambda _path, _target, _backup: None,
            reindex=lambda _path, _target: (_ for _ in ()).throw(
                AcceptanceError("reindex failed")
            ),
            restore_drill=lambda _config: events.append("restore"),
        ),
    )

    assert result["status"] == "failed"
    assert events == []
    assert next(check for check in result["checks"] if check["name"] == "reindex")["status"] == "failed"
    assert next(check for check in result["checks"] if check["name"] == "restore_drill")["status"] == "not_run"


def test_backup_media_loopback_uri_is_rejected(tmp_path: Path) -> None:
    evidence = tmp_path / "media.json"
    evidence.write_text(json.dumps({
        "status": "verified",
        "target": "production",
        "verified_at": "2026-09-11T01:00:00Z",
        "artifact_count": 1,
        "media_uri": "https://localhost/backup",
        "manifest_sha256": "a" * 64,
        "verification_id": "media-check",
        "retention_days": 30,
        "immutable_until": "2026-10-11T01:00:00Z",
        "encrypted": True,
        "offsite": True,
        "immutable": True,
        "provider": "s3",
        "provider_verified": True,
        "remote_exists": True,
        "provider_verification_id": "aws-check-20260911",
        "remote_manifest_sha256": "a" * 64,
    }), encoding="utf-8")

    with pytest.raises(AcceptanceError, match="远端介质 URI"):
        validate_backup_media_evidence(evidence, target="production")


def test_backup_media_manifest_hash_is_bound_to_verified_backup(tmp_path: Path) -> None:
    backup_dir = tmp_path / "careercrew-20260911-010000"
    backup_dir.mkdir()
    manifest = backup_dir / "manifest.json"
    manifest.write_text(json.dumps({
        "format": "careercrew-backup-v1",
        "artifacts": [
            {"path": "postgres.dump"},
            {"path": "files.zip"},
            {"path": "qdrant/careercrew_mm.snapshot"},
        ],
    }) + "\n", encoding="utf-8")
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    evidence = tmp_path / "media.json"
    evidence.write_text(json.dumps({
        "status": "verified",
        "target": "production",
        "verified_at": "2026-09-11T01:00:00Z",
        "artifact_count": 3,
        "media_uri": "s3://release/backup/20260911",
        "manifest_sha256": digest,
        "verification_id": "media-check",
        "retention_days": 30,
        "immutable_until": "2026-10-11T01:00:00Z",
            "encrypted": True,
            "offsite": True,
            "immutable": True,
            "provider": "s3",
            "provider_verified": True,
            "remote_exists": True,
            "provider_verification_id": "aws-check-20260911",
            "remote_manifest_sha256": digest,
        }), encoding="utf-8")

    assert validate_backup_media_evidence(
        evidence, target="production", backup_dir=backup_dir,
    )["artifact_count"] == 3
    evidence_data = json.loads(evidence.read_text(encoding="utf-8"))
    evidence_data["artifact_count"] = 4
    evidence.write_text(json.dumps(evidence_data), encoding="utf-8")
    with pytest.raises(AcceptanceError, match="artifact_count"):
        validate_backup_media_evidence(evidence, target="production", backup_dir=backup_dir)

    evidence_data["artifact_count"] = 3
    evidence.write_text(json.dumps(evidence_data), encoding="utf-8")
    evidence.write_text(evidence.read_text(encoding="utf-8").replace(digest, "a" * 64), encoding="utf-8")
    with pytest.raises(AcceptanceError, match="manifest_sha256"):
        validate_backup_media_evidence(evidence, target="production", backup_dir=backup_dir)
