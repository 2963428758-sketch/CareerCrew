"""Resume master workspace, reusable materials, annotations and export jobs.

Revision ID: 0014_resume_workspace
Revises: 0013_consultation_workspace
"""
from __future__ import annotations

from alembic import op

revision: str = "0014_resume_workspace"
down_revision: str | None = "0013_consultation_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_master_documents (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            title VARCHAR(200) NOT NULL,
            description VARCHAR(1000) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_master_versions (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            master_id UUID NOT NULL REFERENCES resume_master_documents(id) ON DELETE CASCADE,
            parent_version_id UUID REFERENCES resume_master_versions(id) ON DELETE SET NULL,
            label VARCHAR(120) NOT NULL,
            content TEXT NOT NULL,
            kind VARCHAR(20) NOT NULL CHECK (kind IN ('master', 'derived')),
            version_number INTEGER NOT NULL CHECK (version_number > 0),
            content_sha256 CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_experience_materials (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            title VARCHAR(200) NOT NULL,
            context TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT '',
            actions TEXT NOT NULL DEFAULT '',
            results TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_annotations (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            version_id UUID NOT NULL REFERENCES resume_master_versions(id) ON DELETE CASCADE,
            start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
            end_offset INTEGER NOT NULL CHECK (end_offset >= start_offset),
            note VARCHAR(1000) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'resolved')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_export_jobs (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            version_ids JSONB NOT NULL,
            formats JSONB NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'done', 'failed', 'expired')),
            result_zip BYTEA,
            error VARCHAR(300),
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_resume_master_owner_updated "
        "ON resume_master_documents(owner_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_resume_version_owner_master "
        "ON resume_master_versions(owner_id, master_id, version_number DESC)",
        "CREATE INDEX IF NOT EXISTS ix_resume_material_owner_updated "
        "ON resume_experience_materials(owner_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_resume_annotation_owner_version "
        "ON resume_annotations(owner_id, version_id, start_offset)",
        "CREATE INDEX IF NOT EXISTS ix_resume_export_owner_created "
        "ON resume_export_jobs(owner_id, created_at DESC)",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS resume_export_jobs")
    op.execute("DROP TABLE IF EXISTS resume_annotations")
    op.execute("DROP TABLE IF EXISTS resume_experience_materials")
    op.execute("DROP TABLE IF EXISTS resume_master_versions")
    op.execute("DROP TABLE IF EXISTS resume_master_documents")
