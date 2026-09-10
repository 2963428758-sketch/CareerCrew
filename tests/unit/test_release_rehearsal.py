from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import release_rehearsal as rehearsal
from scripts import validate_migrations


def test_database_config_parses_encoded_credentials_and_builds_target_url() -> None:
    config = rehearsal.DatabaseConfig.from_url(
        "postgresql+psycopg://release:p%40ss@127.0.0.1:5544/careercrew?sslmode=require"
    )

    assert config.user == "release"
    assert config.password == "p@ss"
    assert config.database == "careercrew"
    assert rehearsal.database_url_for(config, "careercrew_rehearsal_a1_fresh") == (
        "postgresql+psycopg://release:p%40ss@127.0.0.1:5544/"
        "careercrew_rehearsal_a1_fresh?sslmode=require"
    )


@pytest.mark.parametrize(
    "name",
    [
        "careercrew",
        "careercrew_rehearsal_a1",
        "careercrew_rehearsal_other_fresh",
        "careercrew_rehearsal_a1_fresh;DROP DATABASE careercrew",
    ],
)
def test_database_guard_rejects_source_and_names_outside_run_prefix(name: str) -> None:
    with pytest.raises(ValueError):
        rehearsal.validate_temporary_database(
            name,
            run_prefix="careercrew_rehearsal_a1",
            source_database="careercrew",
        )


def test_database_guard_accepts_only_suffixed_database_for_this_run() -> None:
    rehearsal.validate_temporary_database(
        "careercrew_rehearsal_a1_fresh",
        run_prefix="careercrew_rehearsal_a1",
        source_database="careercrew",
    )


def test_docker_psql_command_uses_dsn_credentials_without_putting_password_in_sql() -> None:
    config = rehearsal.DatabaseConfig.from_url(
        "postgresql://release:p%40ss@localhost:5432/careercrew"
    )

    command = rehearsal.docker_psql_command(
        config,
        container="postgres-test",
        database="postgres",
        arguments=["-t", "-A", "-c", "SELECT 1"],
    )

    assert command == [
        "docker",
        "exec",
        "-e",
        "PGPASSWORD",
        "postgres-test",
        "psql",
        "-U",
        "release",
        "-d",
        "postgres",
        "-t",
        "-A",
        "-c",
        "SELECT 1",
    ]
    assert "p@ss" not in " ".join(command)


def test_docker_admin_rejects_source_database_before_running_command(monkeypatch) -> None:
    config = rehearsal.DatabaseConfig.from_url(
        "postgresql://release:secret@localhost:5432/careercrew"
    )
    postgres = rehearsal.DockerPostgres(
        config,
        "postgres-test",
        run_prefix="careercrew_rehearsal_a1",
    )
    monkeypatch.setattr(
        rehearsal,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("database guard must run before Docker"),
    )

    with pytest.raises(ValueError, match="范围外"):
        postgres.drop_database("careercrew")


def test_managed_databases_cleanup_every_created_database_after_exception() -> None:
    created: list[str] = []
    dropped: list[str] = []
    names = ["careercrew_rehearsal_a1_fresh", "careercrew_rehearsal_a1_restore"]

    with pytest.raises(RuntimeError, match="injected failure"):
        with rehearsal.managed_databases(
            names,
            run_prefix="careercrew_rehearsal_a1",
            source_database="careercrew",
            create=created.append,
            drop=dropped.append,
        ):
            raise RuntimeError("injected failure")

    assert created == names
    assert dropped == list(reversed(names))
    assert "careercrew" not in dropped


def test_managed_databases_reports_cleanup_failure_after_trying_every_database() -> None:
    dropped: list[str] = []
    names = ["careercrew_rehearsal_a1_fresh", "careercrew_rehearsal_a1_restore"]

    def drop(name: str) -> None:
        dropped.append(name)
        if name.endswith("restore"):
            raise RuntimeError("database is busy")

    with pytest.raises(rehearsal.CommandError, match="database is busy"):
        with rehearsal.managed_databases(
            names,
            run_prefix="careercrew_rehearsal_a1",
            source_database="careercrew",
            create=lambda _name: None,
            drop=drop,
        ):
            pass

    assert dropped == list(reversed(names))


def test_failure_migration_is_created_only_in_temporary_copy(tmp_path: Path) -> None:
    source = tmp_path / "source-migrations"
    versions = source / "versions"
    versions.mkdir(parents=True)
    (source / "env.py").write_text("# alembic environment\n", encoding="utf-8")
    (versions / "0008.py").write_text(
        'revision = "0008_prod_hardening"\n', encoding="utf-8"
    )
    workspace = tmp_path / "workspace"

    copied_versions = rehearsal.create_failure_migration_tree(source, workspace)

    assert copied_versions == workspace / "migrations" / "versions"
    assert (copied_versions / "0008.py").read_text(encoding="utf-8") == (
        'revision = "0008_prod_hardening"\n'
    )
    assert (copied_versions / "9999_rehearsal_bad.py").is_file()
    assert sorted(path.name for path in versions.iterdir()) == ["0008.py"]


def test_rehearsal_head_matches_migration_validator() -> None:
    assert rehearsal.EXPECTED_HEAD == validate_migrations.EXPECTED_HEAD


def test_failure_migration_can_be_anchored_to_current_head(tmp_path: Path) -> None:
    source = tmp_path / "source-migrations"
    versions = source / "versions"
    versions.mkdir(parents=True)
    (source / "env.py").write_text("# alembic environment\n", encoding="utf-8")
    (versions / "0016.py").write_text(
        'revision = "0016_workspace_owner_integrity"\n', encoding="utf-8"
    )
    workspace = tmp_path / "workspace"

    copied_versions = rehearsal.create_failure_migration_tree(
        source, workspace, down_revision=rehearsal.EXPECTED_HEAD,
    )

    bad = (copied_versions / "9999_rehearsal_bad.py").read_text(encoding="utf-8")
    assert 'down_revision = "0016_workspace_owner_integrity"' in bad


def test_report_records_real_restore_probe_and_environment() -> None:
    started_at = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    results = [
        rehearsal.CheckResult(
            name="备份恢复",
            passed=True,
            detail="rows=1, payload=synthetic-release-rehearsal",
        )
    ]

    report = rehearsal.render_report(
        run_prefix="careercrew_rehearsal_a1",
        started_at=started_at,
        duration_seconds=3.25,
        source_database="careercrew",
        container="postgres-test",
        results=results,
    )

    assert "careercrew_rehearsal_a1" in report
    assert "rows=1, payload=synthetic-release-rehearsal" in report
    assert "postgres-test" in report
    assert "3.25" in report
    assert "真实开发库数据未进入备份" in report
