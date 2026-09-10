"""人工长期记忆治理事件和 ignored 状态。

Revision ID: 0009_memory_governance
Revises: 0008_prod_hardening
"""
from __future__ import annotations

from alembic import op

revision = "0009_memory_governance"
down_revision = "0008_prod_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0008 is published and immutable; extend the status vocabulary in a new
    # revision so a user can temporarily hide a fact without deleting it.
    op.execute("ALTER TABLE memory_records DROP CONSTRAINT IF EXISTS memory_records_status_check")
    op.execute(
        "ALTER TABLE memory_records ADD CONSTRAINT memory_records_status_check "
        "CHECK (status IN ('active', 'superseded', 'expired', 'deleted', 'ignored', 'quarantined'))"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_record_events (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            memory_id UUID NOT NULL REFERENCES memory_records(id) ON DELETE RESTRICT,
            action VARCHAR(30) NOT NULL CHECK (action IN ('confirm', 'edit', 'ignore', 'expire', 'merge')),
            reason VARCHAR(500) NOT NULL DEFAULT '',
            actor_id VARCHAR(64) NOT NULL,
            before_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            after_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            row_version INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_record_events_owner "
        "ON memory_record_events(owner_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_record_events_memory "
        "ON memory_record_events(memory_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_memory_record_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'memory_record_events is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS memory_record_events_immutable
        ON memory_record_events
        """
    )
    op.execute(
        """
        CREATE TRIGGER memory_record_events_immutable
        BEFORE UPDATE OR DELETE ON memory_record_events
        FOR EACH ROW EXECUTE FUNCTION reject_memory_record_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS memory_record_events_immutable ON memory_record_events")
    op.execute("DROP FUNCTION IF EXISTS reject_memory_record_event_mutation()")
    op.execute("DROP TABLE IF EXISTS memory_record_events")
    op.execute("ALTER TABLE memory_records DROP CONSTRAINT IF EXISTS memory_records_status_check")
    op.execute(
        "ALTER TABLE memory_records ADD CONSTRAINT memory_records_status_check "
        "CHECK (status IN ('active', 'superseded', 'expired', 'deleted', 'quarantined'))"
    )
