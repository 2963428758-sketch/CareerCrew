"""Migration graph, checksum, and live-schema guard tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.validate_migrations import (
    MigrationValidationError,
    build_checksum_manifest,
    read_revision_metadata,
    validate_checksum_manifest,
    validate_revision_graph,
    validate_schema_invariants,
)


def _write_migration(path: Path, revision: str, down_revision: str | None) -> None:
    down = "None" if down_revision is None else repr(down_revision)
    path.write_text(
        f'revision: str = {revision!r}\n' f'down_revision: str | None = {down}\n',
        encoding="utf-8",
    )


def test_read_revision_metadata_accepts_annotated_revision(tmp_path: Path) -> None:
    migration = tmp_path / "0001_initial.py"
    _write_migration(migration, "0001_initial", None)

    metadata = read_revision_metadata(migration)

    assert metadata.revision == "0001_initial"
    assert metadata.down_revision is None


def test_validate_revision_graph_requires_one_linear_head(tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    _write_migration(versions / "0001.py", "0001", None)
    _write_migration(versions / "0002.py", "0002", "0001")

    migrations = validate_revision_graph(versions, expected_head="0002")

    assert [item.revision for item in migrations] == ["0001", "0002"]


@pytest.mark.parametrize(
    "setup, expected_message",
    [
        (
            lambda versions: (
                _write_migration(versions / "a.py", "same", None),
                _write_migration(versions / "b.py", "same", None),
            ),
            "duplicate revision",
        ),
        (
            lambda versions: _write_migration(versions / "a.py", "a", "missing"),
            "unknown down_revision",
        ),
    ],
)
def test_validate_revision_graph_rejects_duplicate_or_missing_revisions(
    tmp_path: Path, setup, expected_message: str
) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    setup(versions)

    with pytest.raises(MigrationValidationError, match=expected_message):
        validate_revision_graph(versions, expected_head="a")


def test_validate_checksum_manifest_rejects_mismatch_and_extra_file(tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    _write_migration(versions / "0001.py", "0001", None)
    manifest = build_checksum_manifest(versions)
    manifest["0001.py"] = "0" * 64
    manifest["removed.py"] = "1" * 64
    manifest_path = tmp_path / "checksums.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(MigrationValidationError, match="checksum mismatch|extra file"):
        validate_checksum_manifest(versions, manifest_path)


def test_build_checksum_manifest_is_stable_across_crlf_and_lf(tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    content = b'revision = "0001"\r\ndown_revision = None\r\n'
    (versions / "0001.py").write_bytes(content)

    manifest = build_checksum_manifest(versions)

    assert manifest["0001.py"] == hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


class _FakeCursor:
    def __init__(self, rows_by_marker: dict[str, list[tuple]]) -> None:
        self.rows_by_marker = rows_by_marker
        self.rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str, params=()) -> None:
        for marker, rows in self.rows_by_marker.items():
            if marker in query:
                self.rows = rows
                return
        raise AssertionError(f"unexpected query: {query}")

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, rows_by_marker: dict[str, list[tuple]]) -> None:
        self.rows_by_marker = rows_by_marker

    def cursor(self):
        return _FakeCursor(self.rows_by_marker)


def _valid_schema_rows() -> dict[str, list[tuple]]:
    tables = [
        ("career_generation_events",),
        ("career_product_events",),
        ("upload_tasks",),
        ("career_share_tokens",),
    ]
    columns = [
        ("career_share_tokens", "token_hash"),
        ("career_share_tokens", "access_count"),
        ("career_share_tokens", "last_accessed_at"),
    ]
    indexes = [
        (name, f"CREATE INDEX {name} ON public.example USING gin (value gin_trgm_ops)")
        for name in (
            "ix_p5_preparation_opportunities_company",
            "ix_p5_preparation_opportunities_title",
            "ix_p5_preparation_opportunities_jd",
            "ix_p5_project_materials_name",
            "ix_p5_project_materials_background",
            "ix_p5_project_materials_results",
            "ix_p5_real_interview_records_company",
            "ix_p5_real_interview_records_title",
            "ix_p5_real_interview_records_overall_reflection",
            "ix_p5_offer_comparisons_company",
            "ix_p5_offer_comparisons_title",
            "ix_p5_offer_comparisons_notes",
            "ix_p5_action_items_title",
            "ix_p5_action_items_note",
        )
    ]
    return {
        "alembic_version": [("0008_prod_hardening",)],
        "information_schema.tables": tables,
        "information_schema.columns": columns,
        "pg_extension": [("pg_trgm",)],
        "pg_indexes": indexes,
    }


def test_validate_schema_invariants_rejects_missing_live_invariant() -> None:
    rows = _valid_schema_rows()
    rows["pg_extension"] = []

    with pytest.raises(MigrationValidationError, match="pg_trgm"):
        validate_schema_invariants(_FakeConnection(rows))


@pytest.mark.parametrize(
    "marker, expected_message",
    [
        ("head", "alembic_version mismatch"),
        ("table", "missing tables"),
        ("column", "missing career_share_tokens columns"),
        ("extension", "pg_trgm"),
        ("index", "missing pg_trgm indexes"),
        ("legacy", "legacy career_share_tokens.token"),
        ("index_definition", "invalid pg_trgm indexes"),
    ],
)
def test_validate_schema_invariants_covers_each_required_negative_case(
    marker: str, expected_message: str
) -> None:
    rows = _valid_schema_rows()
    if marker == "head":
        rows["alembic_version"] = [("0007_version_attribution_shares",)]
    elif marker == "table":
        rows["information_schema.tables"] = rows["information_schema.tables"][1:]
    elif marker == "column":
        rows["information_schema.columns"] = rows["information_schema.columns"][1:]
    elif marker == "extension":
        rows["pg_extension"] = []
    elif marker == "index":
        rows["pg_indexes"] = rows["pg_indexes"][1:]
    elif marker == "index_definition":
        name, _definition = rows["pg_indexes"][0]
        rows["pg_indexes"][0] = (name, f"CREATE INDEX {name} ON public.example USING btree (value)")
    else:
        rows["information_schema.columns"].append(("career_share_tokens", "token"))

    with pytest.raises(MigrationValidationError, match=expected_message):
        validate_schema_invariants(_FakeConnection(rows))


def test_validate_schema_invariants_accepts_complete_schema() -> None:
    validate_schema_invariants(_FakeConnection(_valid_schema_rows()))
