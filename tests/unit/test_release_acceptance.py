"""Fail-closed tests for the local release rehearsal orchestrator."""
from __future__ import annotations

import json
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
)

LOCAL_DATABASE = "postgresql://careercrew:secret@localhost:5432/careercrew"
LOCAL_RESTORE_DATABASE = "postgresql://careercrew:secret@localhost:5432/careercrew_restore_control"


def _local_config(tmp_path: Path, *, restore_approved: bool = False) -> AcceptanceConfig:
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(exist_ok=True)
    return AcceptanceConfig(
        database_url=LOCAL_DATABASE,
        qdrant_url="http://localhost:6333",
        backup_dir=backup_dir,
        qdrant_container=None,
        restore_database_url=LOCAL_RESTORE_DATABASE,
        restore_qdrant_url="http://localhost:6333",
        restore_approved=restore_approved,
        report_path=tmp_path / "local-acceptance.json",
        required_collections=("careercrew_mm", "careercrew_episodic_v2"),
    )


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
        acceptance._default_ownership(_local_config(tmp_path))


def test_rehearsal_rejects_remote_source_endpoints() -> None:
    with pytest.raises(AcceptanceError, match="回环"):
        resolve_config(
            database_url="postgresql://user:secret@prod.example:5432/careercrew",
            qdrant_url="http://qdrant.example:6333",
            environ={},
        )


def test_rehearsal_restore_requires_explicit_isolated_targets() -> None:
    with pytest.raises(AcceptanceError, match="显式"):
        resolve_config(
            database_url=LOCAL_DATABASE,
            qdrant_url="http://localhost:6333",
            environ={"CAREERCREW_RELEASE_RESTORE_DRILL": "1"},
        )


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
        database_url=LOCAL_DATABASE,
        qdrant_url="http://localhost:6333",
        qdrant_api_key="configured-source-key",
        backup_dir=None,
        qdrant_container=None,
        restore_approved=False,
        report_path=Path("acceptance.json"),
    )

    _default_qdrant(config)

    assert calls and all(call["headers"] == {"api-key": "configured-source-key"} for call in calls)


def test_qdrant_url_rejects_invalid_port() -> None:
    with pytest.raises(AcceptanceError, match="QDRANT_URL"):
        resolve_config(
            database_url=LOCAL_DATABASE,
            qdrant_url="",
            environ={"QDRANT_URL": "http://localhost:not-a-port"},
        )


def test_resolve_config_reads_restore_qdrant_key_only_from_environment() -> None:
    config = resolve_config(
        database_url=LOCAL_DATABASE,
        qdrant_url="http://localhost:6333",
        restore_database_url=LOCAL_RESTORE_DATABASE,
        restore_qdrant_url="http://localhost:6333",
        environ={"RESTORE_QDRANT_API_KEY": "restore-qdrant-secret"},
    )

    assert config.restore_qdrant_api_key == "restore-qdrant-secret"
    assert "restore-qdrant-secret" not in repr(config)


def test_restore_adapter_uses_isolated_managed_qdrant_without_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def fake_restore(*args, **kwargs):
        calls["args"] = args
        calls.update(kwargs)
        return "careercrew_restore_20260911010000_test"

    import scripts.release_acceptance as acceptance

    monkeypatch.setattr(acceptance.backup_restore, "restore_drill", fake_restore)
    config = _local_config(tmp_path, restore_approved=True)

    assert _default_restore_drill(config)["cleaned"] is True
    assert calls["qdrant_container"] is None
    assert calls["qdrant_api_key"] is None


def test_restore_drill_requires_explicit_operator_marker(tmp_path: Path) -> None:
    events: list[str] = []
    config = _local_config(tmp_path, restore_approved=False)
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


def test_rehearsal_passes_with_injected_adapters(tmp_path: Path) -> None:
    events: list[str] = []
    config = _local_config(tmp_path, restore_approved=True)
    adapters = AcceptanceAdapters(
        migration_static=lambda: events.append("migration_static"),
        migration_live=lambda _dsn: events.append("migration_live"),
        qdrant=lambda _config: events.append("qdrant"),
        ownership=lambda _config: events.append("ownership"),
        backup_verify=lambda _path: events.append("backup_verify"),
        restore_drill=lambda _config: events.append("restore_drill"),
    )
    result = run_acceptance(config, adapters=adapters)

    assert result["status"] == "rehearsal_passed"
    assert result["target"] == "local"
    assert events == ["migration_static", "migration_live", "qdrant", "ownership", "backup_verify", "restore_drill"]
    assert "secret" not in json.dumps(result, ensure_ascii=False)


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
