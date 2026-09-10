"""Database-level owner integrity for workspace relationships.

Revision ID: 0016_workspace_owner_integrity
Revises: 0015_tool_operations
"""
from __future__ import annotations

from alembic import op

revision: str = "0016_workspace_owner_integrity"
down_revision: str | None = "0015_tool_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A resource UUID alone is not an ownership boundary.  These composite
    # indexes make (resource_id, owner_id) valid FK targets for all new links.
    for statement in (
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_messages_id_user_id "
        "ON messages(id, user_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_conversations_id_user_id "
        "ON conversations(id, user_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_consultation_reports_id_owner_id "
        "ON consultation_reports(id, owner_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_resume_master_documents_id_owner_id "
        "ON resume_master_documents(id, owner_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_resume_master_versions_id_owner_id "
        "ON resume_master_versions(id, owner_id)",
    ):
        op.execute(statement)

    for statement in (
        """
        ALTER TABLE conversation_bookmarks
        ADD CONSTRAINT fk_workspace_bookmark_message_owner
        FOREIGN KEY (message_id, owner_id) REFERENCES messages(id, user_id)
        ON DELETE CASCADE
        """,
        """
        ALTER TABLE conversation_branches
        ADD CONSTRAINT fk_workspace_branch_source_owner
        FOREIGN KEY (source_thread_id, owner_id) REFERENCES conversations(id, user_id)
        ON DELETE CASCADE
        """,
        """
        ALTER TABLE conversation_branches
        ADD CONSTRAINT fk_workspace_branch_cutoff_owner
        FOREIGN KEY (cutoff_message_id, owner_id) REFERENCES messages(id, user_id)
        ON DELETE CASCADE
        """,
        """
        ALTER TABLE conversation_branches
        ADD CONSTRAINT fk_workspace_branch_target_owner
        FOREIGN KEY (branch_thread_id, owner_id) REFERENCES conversations(id, user_id)
        ON DELETE CASCADE
        """,
        """
        ALTER TABLE workspace_action_items
        ADD CONSTRAINT fk_workspace_action_message_owner
        FOREIGN KEY (source_message_id, owner_id) REFERENCES messages(id, user_id)
        ON DELETE CASCADE
        """,
        """
        ALTER TABLE consultation_reports
        ADD CONSTRAINT fk_consultation_report_message_owner
        FOREIGN KEY (source_message_id, owner_id) REFERENCES messages(id, user_id)
        ON DELETE CASCADE
        """,
        """
        ALTER TABLE consultation_plans
        ADD CONSTRAINT fk_consultation_plan_report_owner
        FOREIGN KEY (report_id, owner_id) REFERENCES consultation_reports(id, owner_id)
        ON DELETE CASCADE
        """,
        """
        ALTER TABLE resume_master_versions
        ADD CONSTRAINT fk_resume_version_master_owner
        FOREIGN KEY (master_id, owner_id) REFERENCES resume_master_documents(id, owner_id)
        ON DELETE CASCADE
        """,
        """
        ALTER TABLE resume_master_versions
        ADD CONSTRAINT fk_resume_version_parent_owner
        FOREIGN KEY (parent_version_id, owner_id) REFERENCES resume_master_versions(id, owner_id)
        ON DELETE NO ACTION
        """,
        """
        ALTER TABLE resume_annotations
        ADD CONSTRAINT fk_resume_annotation_version_owner
        FOREIGN KEY (version_id, owner_id) REFERENCES resume_master_versions(id, owner_id)
        ON DELETE CASCADE
        """,
    ):
        op.execute(statement)


def downgrade() -> None:
    for table, constraint in (
        ("resume_annotations", "fk_resume_annotation_version_owner"),
        ("resume_master_versions", "fk_resume_version_parent_owner"),
        ("resume_master_versions", "fk_resume_version_master_owner"),
        ("consultation_plans", "fk_consultation_plan_report_owner"),
        ("consultation_reports", "fk_consultation_report_message_owner"),
        ("workspace_action_items", "fk_workspace_action_message_owner"),
        ("conversation_branches", "fk_workspace_branch_target_owner"),
        ("conversation_branches", "fk_workspace_branch_cutoff_owner"),
        ("conversation_branches", "fk_workspace_branch_source_owner"),
        ("conversation_bookmarks", "fk_workspace_bookmark_message_owner"),
    ):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
    for statement in (
        "DROP INDEX IF EXISTS ux_resume_master_versions_id_owner_id",
        "DROP INDEX IF EXISTS ux_resume_master_documents_id_owner_id",
        "DROP INDEX IF EXISTS ux_consultation_reports_id_owner_id",
        "DROP INDEX IF EXISTS ux_conversations_id_user_id",
        "DROP INDEX IF EXISTS ux_messages_id_user_id",
    ):
        op.execute(statement)
