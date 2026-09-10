"""Validate Alembic history, immutable migration checksums, and live schema.

The validator deliberately parses migration metadata instead of importing or
executing migration modules.  ``migrations/checksums.json`` is a committed
allow-list: changing a published migration requires an explicit review and a
new migration, never an in-place checksum refresh.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from careercrew_core.pg_pool import normalize_dsn

ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = ROOT / "migrations" / "versions"
CHECKSUM_MANIFEST = ROOT / "migrations" / "checksums.json"
EXPECTED_HEAD = "0008_prod_hardening"

EXPECTED_TABLES = frozenset(
    {
        "career_generation_events",
        "career_product_events",
        "upload_tasks",
        "career_share_tokens",
    }
)
EXPECTED_SHARE_COLUMNS = frozenset(
    {"token_hash", "access_count", "last_accessed_at"}
)
EXPECTED_INDEX_TARGETS: Mapping[str, tuple[str, str]] = {
    "ix_p5_preparation_opportunities_company": ("preparation_opportunities", "company"),
    "ix_p5_preparation_opportunities_title": ("preparation_opportunities", "title"),
    "ix_p5_preparation_opportunities_jd": ("preparation_opportunities", "jd"),
    "ix_p5_project_materials_name": ("project_materials", "name"),
    "ix_p5_project_materials_background": ("project_materials", "background"),
    "ix_p5_project_materials_results": ("project_materials", "results"),
    "ix_p5_real_interview_records_company": ("real_interview_records", "company"),
    "ix_p5_real_interview_records_title": ("real_interview_records", "title"),
    "ix_p5_real_interview_records_overall_reflection": (
        "real_interview_records",
        "overall_reflection",
    ),
    "ix_p5_offer_comparisons_company": ("offer_comparisons", "company"),
    "ix_p5_offer_comparisons_title": ("offer_comparisons", "title"),
    "ix_p5_offer_comparisons_notes": ("offer_comparisons", "notes"),
    "ix_p5_action_items_title": ("action_items", "title"),
    "ix_p5_action_items_note": ("action_items", "note"),
}
EXPECTED_INDEXES = frozenset(EXPECTED_INDEX_TARGETS)


class MigrationValidationError(ValueError):
    """Raised when migration history or the expected schema is unsafe."""


@dataclass(frozen=True)
class RevisionMetadata:
    path: Path
    revision: str
    down_revision: str | None


def _migration_paths(versions_dir: Path) -> list[Path]:
    versions_dir = Path(versions_dir)
    if not versions_dir.is_dir():
        raise MigrationValidationError(f"migration directory not found: {versions_dir}")
    return sorted(
        path for path in versions_dir.glob("*.py") if path.name != "__init__.py"
    )


def _assignment_value(module: ast.Module, name: str, path: Path) -> Any:
    values: list[Any] = []
    for node in module.body:
        target = None
        value_node = None
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target = node.targets[0].id
                value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
            value_node = node.value
        if target != name or value_node is None:
            continue
        try:
            values.append(ast.literal_eval(value_node))
        except (ValueError, SyntaxError) as exc:
            raise MigrationValidationError(
                f"{path.name}: {name} must be a literal"
            ) from exc
    if len(values) != 1:
        raise MigrationValidationError(
            f"{path.name}: expected exactly one {name} assignment"
        )
    return values[0]


def read_revision_metadata(path: Path) -> RevisionMetadata:
    """Read ``revision`` and ``down_revision`` without executing the file."""

    path = Path(path)
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise MigrationValidationError(f"{path.name}: cannot parse migration") from exc

    revision = _assignment_value(module, "revision", path)
    down_revision = _assignment_value(module, "down_revision", path)
    if not isinstance(revision, str) or not revision:
        raise MigrationValidationError(f"{path.name}: revision must be a non-empty string")
    if down_revision is not None and not isinstance(down_revision, str):
        raise MigrationValidationError(
            f"{path.name}: down_revision must be a string or None"
        )
    return RevisionMetadata(path, revision, down_revision)


def validate_revision_graph(
    versions_dir: Path = VERSIONS_DIR,
    *,
    expected_head: str = EXPECTED_HEAD,
) -> list[RevisionMetadata]:
    """Validate that the migration directory is a single complete linear chain."""

    migrations = [read_revision_metadata(path) for path in _migration_paths(versions_dir)]
    if not migrations:
        raise MigrationValidationError("no migration files found")

    by_revision: dict[str, RevisionMetadata] = {}
    duplicate_revisions: set[str] = set()
    for migration in migrations:
        if migration.revision in by_revision:
            duplicate_revisions.add(migration.revision)
        by_revision[migration.revision] = migration
    if duplicate_revisions:
        values = ", ".join(sorted(duplicate_revisions))
        raise MigrationValidationError(f"duplicate revision: {values}")

    unknown_down_revisions = sorted(
        {
            migration.down_revision
            for migration in migrations
            if migration.down_revision is not None
            and migration.down_revision not in by_revision
        }
    )
    if unknown_down_revisions:
        raise MigrationValidationError(
            "unknown down_revision: " + ", ".join(unknown_down_revisions)
        )

    roots = [migration for migration in migrations if migration.down_revision is None]
    if len(roots) != 1:
        raise MigrationValidationError(
            f"expected one migration root, found {len(roots)}"
        )

    referenced = {
        migration.down_revision
        for migration in migrations
        if migration.down_revision is not None
    }
    heads = [migration for migration in migrations if migration.revision not in referenced]
    if len(heads) != 1:
        raise MigrationValidationError(f"expected one migration head, found {len(heads)}")
    if heads[0].revision != expected_head:
        raise MigrationValidationError(
            f"unexpected migration head: {heads[0].revision}; expected {expected_head}"
        )

    # The root/head checks and one-parent metadata prove the usual Alembic
    # shape, but walking the chain also rejects a disconnected component.
    current = roots[0].revision
    visited: set[str] = set()
    while current not in visited:
        visited.add(current)
        children = [
            migration.revision
            for migration in migrations
            if migration.down_revision == current
        ]
        if len(children) > 1:
            raise MigrationValidationError(
                f"migration graph is branched at {current}: {', '.join(sorted(children))}"
            )
        if not children:
            break
        current = children[0]
    if len(visited) != len(migrations) or current != expected_head:
        raise MigrationValidationError("migration graph contains a disconnected or cyclic revision")
    return migrations


def build_checksum_manifest(versions_dir: Path = VERSIONS_DIR) -> dict[str, str]:
    """Build the deterministic filename-to-SHA256 migration manifest."""

    return {
        path.name: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for path in _migration_paths(versions_dir)
    }


def validate_checksum_manifest(
    versions_dir: Path = VERSIONS_DIR,
    manifest: Path | Mapping[str, str] = CHECKSUM_MANIFEST,
) -> None:
    """Require exact filename and SHA-256 equality with the committed manifest."""

    if isinstance(manifest, Mapping):
        expected = dict(manifest)
    else:
        manifest_path = Path(manifest)
        try:
            expected = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MigrationValidationError("cannot read migration checksum manifest") from exc
    if not isinstance(expected, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in expected.items()
    ):
        raise MigrationValidationError("migration checksum manifest must be a filename/hash object")

    actual = build_checksum_manifest(versions_dir)
    missing = sorted(set(actual) - set(expected))
    extra = sorted(set(expected) - set(actual))
    mismatched = sorted(
        filename
        for filename in set(actual) & set(expected)
        if actual[filename] != expected[filename]
    )
    problems: list[str] = []
    if missing:
        problems.append("missing file in manifest: " + ", ".join(missing))
    if extra:
        problems.append("extra file in manifest: " + ", ".join(extra))
    if mismatched:
        problems.append("checksum mismatch: " + ", ".join(mismatched))
    if problems:
        raise MigrationValidationError("; ".join(problems))


def _row_value(row: Any, index: int) -> Any:
    if isinstance(row, Mapping):
        keys = ("version_num", "table_name", "column_name", "extname", "indexname")
        return row.get(keys[index])
    return row[index]


def _index_definition(row: Any) -> Any:
    if isinstance(row, Mapping):
        return row.get("indexdef")
    return row[1]


def _index_definition_matches_target(index_name: Any, index_definition: Any) -> bool:
    target = EXPECTED_INDEX_TARGETS.get(index_name)
    if target is None or not isinstance(index_definition, str):
        return False
    table, column = target
    normalized = " ".join(index_definition.lower().split())
    expected_target = rf"\bon\s+public\.{re.escape(table)}\s+using\s+gin\s*\(\s*{re.escape(column)}\s+gin_trgm_ops\s*\)"
    return re.search(expected_target, normalized) is not None


def _fetchall(cursor: Any, query: str) -> list[Any]:
    cursor.execute(query)
    return list(cursor.fetchall())


def validate_schema_invariants(
    connection: Any,
    *,
    expected_head: str = EXPECTED_HEAD,
) -> None:
    """Validate the production schema using a DB-API/psycopg connection."""

    cursor = connection.cursor()
    try:
        version_rows = _fetchall(cursor, "SELECT version_num FROM alembic_version")
        versions = {_row_value(row, 0) for row in version_rows}
        if versions != {expected_head}:
            raise MigrationValidationError(
                f"alembic_version mismatch: expected {expected_head}, found {sorted(versions)}"
            )

        table_rows = _fetchall(
            cursor,
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN (
                'career_generation_events', 'career_product_events',
                'upload_tasks', 'career_share_tokens'
              )
            """,
        )
        tables = {_row_value(row, 0) for row in table_rows}
        missing_tables = sorted(EXPECTED_TABLES - tables)
        if missing_tables:
            raise MigrationValidationError("missing tables: " + ", ".join(missing_tables))

        column_rows = _fetchall(
            cursor,
            """
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN (
                'career_generation_events', 'career_product_events',
                'upload_tasks', 'career_share_tokens'
              )
            """,
        )
        share_columns = {
            _row_value(row, 1)
            for row in column_rows
            if _row_value(row, 0) == "career_share_tokens"
        }
        missing_columns = sorted(EXPECTED_SHARE_COLUMNS - share_columns)
        if missing_columns:
            raise MigrationValidationError(
                "missing career_share_tokens columns: " + ", ".join(missing_columns)
            )
        if "token" in share_columns:
            raise MigrationValidationError(
                "legacy career_share_tokens.token column is still present"
            )

        extension_rows = _fetchall(
            cursor,
            "SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'",
        )
        extensions = {_row_value(row, 0) for row in extension_rows}
        if "pg_trgm" not in extensions:
            raise MigrationValidationError("missing PostgreSQL extension: pg_trgm")

        index_rows = _fetchall(
            cursor,
            """
            SELECT indexname, indexdef FROM pg_indexes
            WHERE schemaname = 'public' AND indexname LIKE 'ix_p5_%'
            """,
        )
        indexes = {_row_value(row, 0) for row in index_rows}
        missing_indexes = sorted(EXPECTED_INDEXES - indexes)
        if missing_indexes:
            raise MigrationValidationError(
                "missing pg_trgm indexes: " + ", ".join(missing_indexes)
            )
        invalid_indexes = sorted(
            _row_value(row, 0)
            for row in index_rows
            if _row_value(row, 0) in EXPECTED_INDEXES
            and not _index_definition_matches_target(_row_value(row, 0), _index_definition(row))
        )
        if invalid_indexes:
            raise MigrationValidationError(
                "invalid pg_trgm indexes: " + ", ".join(invalid_indexes)
            )
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            close()


def validate_static(
    versions_dir: Path = VERSIONS_DIR,
    manifest: Path | Mapping[str, str] = CHECKSUM_MANIFEST,
) -> None:
    validate_revision_graph(versions_dir)
    validate_checksum_manifest(versions_dir, manifest)


def _redact_error(value: str) -> str:
    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", value)


def _validate_database(database_url: str) -> None:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - only affects a CLI environment
        raise MigrationValidationError("psycopg is required for --database-url") from exc
    try:
        connection = psycopg.connect(normalize_dsn(database_url))
    except Exception as exc:  # noqa: BLE001 - CLI converts driver errors to one-line output
        raise MigrationValidationError(
            f"database connection failed: {_redact_error(str(exc))[:500]}"
        ) from exc
    try:
        validate_schema_invariants(connection)
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--static", action="store_true", help="validate revision graph and checksums")
    mode.add_argument("--database-url", help="PostgreSQL URL for the live schema check")
    args = parser.parse_args(argv)
    try:
        if args.static:
            validate_static()
            print("migration static validation: OK")
        else:
            validate_static()
            _validate_database(args.database_url)
            print("migration schema validation: OK")
    except MigrationValidationError as exc:
        print(f"migration validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
