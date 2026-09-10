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
EXPECTED_HEAD = "0016_workspace_owner_integrity"

EXPECTED_TABLES = frozenset(
    {
        "career_generation_events",
        "career_product_events",
        "upload_tasks",
        "career_share_tokens",
        "memory_record_events",
        "knowledge_documents",
        "knowledge_document_versions",
        "knowledge_document_chunks",
        "knowledge_citation_events",
        "usage_budgets",
        "usage_reservations",
        "usage_events",
        "conversation_bookmarks",
        "conversation_branches",
        "workspace_action_items",
        "consultation_reports",
        "consultation_plans",
        "resume_master_documents",
        "resume_master_versions",
        "resume_experience_materials",
        "resume_annotations",
        "resume_export_jobs",
        "tool_policies",
        "tool_policy_audit",
    }
)
EXPECTED_SHARE_COLUMNS = frozenset(
    {"token_hash", "access_count", "last_accessed_at"}
)
EXPECTED_KNOWLEDGE_COLUMNS: Mapping[str, frozenset[str]] = {
    "knowledge_documents": frozenset(
        {"owner_id", "name", "visibility", "status", "active_version_id", "expires_at", "credibility"}
    ),
    "knowledge_document_versions": frozenset(
        {"document_id", "version_number", "content_sha256", "size_bytes", "status", "indexed_at"}
    ),
    "knowledge_document_chunks": frozenset(
        {"version_id", "ordinal", "page", "text", "text_hash", "index_status", "qdrant_point_id"}
    ),
    "knowledge_citation_events": frozenset(
        {"owner_id", "document_id", "version_id", "chunk_id", "request_id", "count", "first_at", "last_at"}
    ),
}
EXPECTED_USAGE_COLUMNS: Mapping[str, frozenset[str]] = {
    "usage_budgets": frozenset(
        {"owner_id", "scope_type", "scope_key", "period", "token_limit", "cost_limit_usd", "soft_limit_ratio", "downgrade_model", "enabled"}
    ),
    "usage_reservations": frozenset(
        {"owner_id", "module", "provider", "model", "estimated_tokens", "estimated_cost_usd", "status", "source_request_id"}
    ),
    "usage_events": frozenset(
        {"owner_id", "module", "provider", "model", "input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd", "pricing_version", "pricing_status", "status", "reservation_id", "source_event_id"}
    ),
}
EXPECTED_WORKSPACE_COLUMNS: Mapping[str, frozenset[str]] = {
    "conversation_bookmarks": frozenset(
        {"owner_id", "message_id", "note", "tags", "created_at", "updated_at"}
    ),
    "conversation_branches": frozenset(
        {"owner_id", "source_thread_id", "cutoff_message_id", "branch_thread_id", "title", "message_count", "created_at"}
    ),
    "workspace_action_items": frozenset(
        {"owner_id", "source_message_id", "title", "note", "due_date", "status", "created_at", "updated_at"}
    ),
}
EXPECTED_CONSULTATION_COLUMNS: Mapping[str, frozenset[str]] = {
    "consultation_reports": frozenset(
        {"owner_id", "source_message_id", "report_json", "status", "version", "created_at", "updated_at"}
    ),
    "consultation_plans": frozenset(
        {"owner_id", "report_id", "title", "steps_json", "status", "version", "created_at", "updated_at"}
    ),
}
EXPECTED_RESUME_COLUMNS: Mapping[str, frozenset[str]] = {
    "resume_master_documents": frozenset(
        {"owner_id", "title", "description", "created_at", "updated_at"}
    ),
    "resume_master_versions": frozenset(
        {"owner_id", "master_id", "parent_version_id", "label", "content", "kind", "version_number", "content_sha256", "created_at"}
    ),
    "resume_experience_materials": frozenset(
        {"owner_id", "title", "context", "role", "actions", "results", "tags", "created_at", "updated_at"}
    ),
    "resume_annotations": frozenset(
        {"owner_id", "version_id", "start_offset", "end_offset", "note", "status", "created_at", "updated_at"}
    ),
    "resume_export_jobs": frozenset(
        {"owner_id", "version_ids", "formats", "status", "result_zip", "error", "expires_at", "created_at", "updated_at"}
    ),
}
EXPECTED_TOOL_COLUMNS: Mapping[str, frozenset[str]] = {
    "tool_policies": frozenset(
        {"tool_id", "enabled", "reason", "updated_by", "updated_at"}
    ),
    "tool_policy_audit": frozenset(
        {"actor_id", "tool_id", "old_enabled", "new_enabled", "reason", "created_at"}
    ),
}
EXPECTED_OWNER_CONSTRAINTS = frozenset(
    {
        "fk_workspace_bookmark_message_owner",
        "fk_workspace_branch_source_owner",
        "fk_workspace_branch_cutoff_owner",
        "fk_workspace_branch_target_owner",
        "fk_workspace_action_message_owner",
        "fk_consultation_report_message_owner",
        "fk_consultation_plan_report_owner",
        "fk_resume_version_master_owner",
        "fk_resume_version_parent_owner",
        "fk_resume_annotation_version_owner",
    }
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
                'upload_tasks', 'career_share_tokens', 'memory_record_events',
                'knowledge_documents', 'knowledge_document_versions',
                'knowledge_document_chunks', 'knowledge_citation_events',
                'usage_budgets', 'usage_reservations', 'usage_events'
                , 'conversation_bookmarks', 'conversation_branches',
                'workspace_action_items'
                , 'consultation_reports', 'consultation_plans'
                , 'resume_master_documents', 'resume_master_versions',
                'resume_experience_materials', 'resume_annotations', 'resume_export_jobs'
                , 'tool_policies', 'tool_policy_audit'
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
                'upload_tasks', 'career_share_tokens', 'memory_record_events',
                'knowledge_documents', 'knowledge_document_versions',
                'knowledge_document_chunks', 'knowledge_citation_events',
                'usage_budgets', 'usage_reservations', 'usage_events'
                , 'conversation_bookmarks', 'conversation_branches',
                'workspace_action_items'
                , 'consultation_reports', 'consultation_plans'
                , 'resume_master_documents', 'resume_master_versions',
                'resume_experience_materials', 'resume_annotations', 'resume_export_jobs'
                , 'tool_policies', 'tool_policy_audit'
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

        columns_by_table: dict[str, set[Any]] = {}
        for row in column_rows:
            columns_by_table.setdefault(_row_value(row, 0), set()).add(_row_value(row, 1))
        missing_knowledge_columns = {
            table: sorted(required - columns_by_table.get(table, set()))
            for table, required in EXPECTED_KNOWLEDGE_COLUMNS.items()
            if required - columns_by_table.get(table, set())
        }
        if missing_knowledge_columns:
            detail = "; ".join(
                f"{table}: {', '.join(columns)}"
                for table, columns in sorted(missing_knowledge_columns.items())
            )
            raise MigrationValidationError("missing knowledge columns: " + detail)

        missing_usage_columns = {
            table: sorted(required - columns_by_table.get(table, set()))
            for table, required in EXPECTED_USAGE_COLUMNS.items()
            if required - columns_by_table.get(table, set())
        }
        if missing_usage_columns:
            detail = "; ".join(
                f"{table}: {', '.join(columns)}"
                for table, columns in sorted(missing_usage_columns.items())
            )
            raise MigrationValidationError("missing usage columns: " + detail)

        missing_workspace_columns = {
            table: sorted(required - columns_by_table.get(table, set()))
            for table, required in EXPECTED_WORKSPACE_COLUMNS.items()
            if required - columns_by_table.get(table, set())
        }
        if missing_workspace_columns:
            detail = "; ".join(
                f"{table}: {', '.join(columns)}"
                for table, columns in sorted(missing_workspace_columns.items())
            )
            raise MigrationValidationError("missing workspace columns: " + detail)

        missing_consultation_columns = {
            table: sorted(required - columns_by_table.get(table, set()))
            for table, required in EXPECTED_CONSULTATION_COLUMNS.items()
            if required - columns_by_table.get(table, set())
        }
        if missing_consultation_columns:
            detail = "; ".join(
                f"{table}: {', '.join(columns)}"
                for table, columns in sorted(missing_consultation_columns.items())
            )
            raise MigrationValidationError("missing consultation columns: " + detail)

        missing_resume_columns = {
            table: sorted(required - columns_by_table.get(table, set()))
            for table, required in EXPECTED_RESUME_COLUMNS.items()
            if required - columns_by_table.get(table, set())
        }
        if missing_resume_columns:
            detail = "; ".join(
                f"{table}: {', '.join(columns)}"
                for table, columns in sorted(missing_resume_columns.items())
            )
            raise MigrationValidationError("missing resume workspace columns: " + detail)

        missing_tool_columns = {
            table: sorted(required - columns_by_table.get(table, set()))
            for table, required in EXPECTED_TOOL_COLUMNS.items()
            if required - columns_by_table.get(table, set())
        }
        if missing_tool_columns:
            detail = "; ".join(
                f"{table}: {', '.join(columns)}"
                for table, columns in sorted(missing_tool_columns.items())
            )
            raise MigrationValidationError("missing tool columns: " + detail)

        constraint_rows = _fetchall(
            cursor,
            """
            SELECT conname FROM pg_constraint
            WHERE connamespace = 'public'::regnamespace
              AND conname IN (
                'fk_workspace_bookmark_message_owner',
                'fk_workspace_branch_source_owner',
                'fk_workspace_branch_cutoff_owner',
                'fk_workspace_branch_target_owner',
                'fk_workspace_action_message_owner',
                'fk_consultation_report_message_owner',
                'fk_consultation_plan_report_owner',
                'fk_resume_version_master_owner',
                'fk_resume_version_parent_owner',
                'fk_resume_annotation_version_owner'
              )
            """,
        )
        constraints = {_row_value(row, 0) for row in constraint_rows}
        missing_constraints = sorted(EXPECTED_OWNER_CONSTRAINTS - constraints)
        if missing_constraints:
            raise MigrationValidationError(
                "missing owner integrity constraints: " + ", ".join(missing_constraints)
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
