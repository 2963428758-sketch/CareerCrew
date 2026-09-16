"""Keep raw upload identity separate from mutable governed chunk content.

Revision ID: 0017_knowledge_source_identity
Revises: 0016_workspace_owner_integrity
"""
from __future__ import annotations

from alembic import op

revision: str = "0017_knowledge_source_identity"
down_revision: str | None = "0016_workspace_owner_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_document_versions "
        "ADD COLUMN IF NOT EXISTS source_content_sha256 CHAR(64)"
    )
    op.execute(
        "ALTER TABLE knowledge_document_versions "
        "ADD COLUMN IF NOT EXISTS source_size_bytes BIGINT"
    )
    op.execute(
        "UPDATE knowledge_document_versions "
        "SET source_content_sha256=content_sha256 "
        "WHERE source_content_sha256 IS NULL"
    )
    op.execute(
        "UPDATE knowledge_document_versions "
        "SET source_size_bytes=size_bytes "
        "WHERE source_size_bytes IS NULL"
    )
    op.execute(
        "ALTER TABLE knowledge_document_versions "
        "ALTER COLUMN source_content_sha256 SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE knowledge_document_versions "
        "ALTER COLUMN source_size_bytes SET NOT NULL"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conname='knowledge_versions_source_sha256_ck') THEN "
        "ALTER TABLE knowledge_document_versions ADD CONSTRAINT "
        "knowledge_versions_source_sha256_ck CHECK "
        "(source_content_sha256 ~ '^[0-9a-fA-F]{64}$'); "
        "END IF; END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conname='knowledge_versions_source_size_ck') THEN "
        "ALTER TABLE knowledge_document_versions ADD CONSTRAINT "
        "knowledge_versions_source_size_ck CHECK (source_size_bytes >= 0); "
        "END IF; END $$"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_versions_source_sha256 "
        "ON knowledge_document_versions(document_id, source_content_sha256)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_versions_source_sha256")
    op.execute(
        "ALTER TABLE knowledge_document_versions "
        "DROP CONSTRAINT IF EXISTS knowledge_versions_source_size_ck"
    )
    op.execute(
        "ALTER TABLE knowledge_document_versions "
        "DROP CONSTRAINT IF EXISTS knowledge_versions_source_sha256_ck"
    )
    op.execute(
        "ALTER TABLE knowledge_document_versions "
        "DROP COLUMN IF EXISTS source_size_bytes"
    )
    op.execute(
        "ALTER TABLE knowledge_document_versions "
        "DROP COLUMN IF EXISTS source_content_sha256"
    )
