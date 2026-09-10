"""Owner-scoped opportunities, immutable resume versions, and session snapshots.

Revision ID: 0004_job_preparation
Revises: 0003_user_settings

Auth may use a separate database: owner_id is not an auth-table foreign key.
Account removal explicitly clears preparation data through its independent store.
"""
from alembic import op

revision = "0004_job_preparation"
down_revision = "0003_user_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE preparation_opportunities (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            company VARCHAR(200) NOT NULL CHECK (length(trim(company)) > 0),
            title VARCHAR(200) NOT NULL CHECK (length(trim(title)) > 0),
            jd TEXT NOT NULL CHECK (length(jd) BETWEEN 1 AND 30000),
            city VARCHAR(200) NOT NULL DEFAULT '', salary VARCHAR(200) NOT NULL DEFAULT '',
            source VARCHAR(100) NOT NULL DEFAULT '', url VARCHAR(2000) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, id)
        )
    """)
    op.execute("""
        CREATE INDEX ix_preparation_opportunities_owner_updated
        ON preparation_opportunities (owner_id, updated_at DESC, id DESC)
    """)
    op.execute("""
        CREATE TABLE preparation_resume_versions (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, opportunity_id TEXT NOT NULL,
            label VARCHAR(120) NOT NULL CHECK (length(trim(label)) > 0),
            content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 50000),
            original_content TEXT NOT NULL DEFAULT '' CHECK (length(original_content) <= 50000),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, opportunity_id, id),
            FOREIGN KEY (owner_id, opportunity_id)
                REFERENCES preparation_opportunities (owner_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE INDEX ix_preparation_versions_owner_opportunity_created
        ON preparation_resume_versions (owner_id, opportunity_id, created_at DESC, id DESC)
    """)
    op.execute("""
        CREATE TABLE preparation_sessions (
            thread_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            module TEXT NOT NULL CHECK (module IN ('resume', 'interview')),
            opportunity_id TEXT NOT NULL, resume_version_id TEXT NOT NULL,
            company VARCHAR(200) NOT NULL, title VARCHAR(200) NOT NULL, jd TEXT NOT NULL,
            resume_content TEXT NOT NULL, resume_label VARCHAR(120) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (owner_id, opportunity_id, resume_version_id)
                REFERENCES preparation_resume_versions (owner_id, opportunity_id, id) ON DELETE CASCADE,
            CHECK ((module = 'resume' AND thread_id LIKE 'r-prep-%')
                OR (module = 'interview' AND thread_id LIKE 'i-prep-%'))
        )
    """)
    op.execute("""
        CREATE INDEX ix_preparation_sessions_owner_version
        ON preparation_sessions (owner_id, opportunity_id, resume_version_id)
    """)


def downgrade() -> None:
    op.drop_table("preparation_sessions")
    op.drop_table("preparation_resume_versions")
    op.drop_table("preparation_opportunities")
