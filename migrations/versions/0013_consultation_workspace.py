"""Explainable consultation reports and explicit execution-plan drafts.

Revision ID: 0013_consultation_workspace
Revises: 0012_workspace_traceability
"""
from __future__ import annotations

from alembic import op

revision: str = "0013_consultation_workspace"
down_revision: str | None = "0012_workspace_traceability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS consultation_reports (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            source_message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            report_json JSONB NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'confirmed')),
            version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, source_message_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS consultation_plans (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            report_id UUID NOT NULL REFERENCES consultation_reports(id) ON DELETE CASCADE,
            title VARCHAR(200) NOT NULL,
            steps_json JSONB NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'confirmed')),
            version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_consultation_reports_owner_updated "
        "ON consultation_reports(owner_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_consultation_plans_owner_report "
        "ON consultation_plans(owner_id, report_id, updated_at DESC)",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS consultation_plans")
    op.execute("DROP TABLE IF EXISTS consultation_reports")
