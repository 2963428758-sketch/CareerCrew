"""Conversation workspace links: bookmarks, bounded branches, and action items.

Revision ID: 0012_workspace_traceability
Revises: 0011_usage_budgets
"""
from __future__ import annotations

from alembic import op

revision: str = "0012_workspace_traceability"
down_revision: str | None = "0011_usage_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_bookmarks (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            note TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, message_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_branches (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            source_thread_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            cutoff_message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            branch_thread_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            message_count INTEGER NOT NULL CHECK (message_count >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, branch_thread_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_action_items (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            source_message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
            title VARCHAR(200) NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            due_date DATE,
            status VARCHAR(20) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'done', 'dismissed')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_workspace_bookmarks_owner_updated "
        "ON conversation_bookmarks(owner_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_branches_owner_created "
        "ON conversation_branches(owner_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_actions_owner_status "
        "ON workspace_action_items(owner_id, status, updated_at DESC)",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workspace_action_items")
    op.execute("DROP TABLE IF EXISTS conversation_branches")
    op.execute("DROP TABLE IF EXISTS conversation_bookmarks")
