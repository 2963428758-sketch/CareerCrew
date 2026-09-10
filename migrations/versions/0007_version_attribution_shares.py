"""简历版本归因（投递所用版本）与导师只读分享令牌。

Revision ID: 0007_version_attribution_shares
Revises: 0006_job_contacts
"""
from alembic import op

revision = "0007_version_attribution_shares"
down_revision = "0006_job_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE preparation_opportunities
            ADD COLUMN IF NOT EXISTS applied_version_id TEXT NOT NULL DEFAULT ''
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS career_share_tokens (
            token TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('opportunity', 'resume_version')),
            ref_id TEXT NOT NULL,
            mask_pii BOOLEAN NOT NULL DEFAULT FALSE,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_career_share_tokens_owner
        ON career_share_tokens (owner_id, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS career_share_tokens")
    op.execute("ALTER TABLE preparation_opportunities DROP COLUMN IF EXISTS applied_version_id")
