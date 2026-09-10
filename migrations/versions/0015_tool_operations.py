"""Tool policy overrides and administrator audit history.

Revision ID: 0015_tool_operations
Revises: 0014_resume_workspace
"""
from __future__ import annotations

from alembic import op

revision: str = "0015_tool_operations"
down_revision: str | None = "0014_resume_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_policies (
            tool_id VARCHAR(150) PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            reason VARCHAR(500) NOT NULL DEFAULT '',
            updated_by VARCHAR(64) NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_policy_audit (
            id UUID PRIMARY KEY,
            actor_id VARCHAR(64) NOT NULL,
            tool_id VARCHAR(150) NOT NULL,
            old_enabled BOOLEAN NOT NULL,
            new_enabled BOOLEAN NOT NULL,
            reason VARCHAR(500) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tool_policy_audit_tool_time "
        "ON tool_policy_audit(tool_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tool_policy_audit")
    op.execute("DROP TABLE IF EXISTS tool_policies")
