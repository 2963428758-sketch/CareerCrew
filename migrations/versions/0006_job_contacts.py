"""联系人与内推管理：为岗位关联招聘者、面试官、内推人与下次联系时间。

Revision ID: 0006_job_contacts
Revises: 0005_job_lifecycle
"""
from alembic import op

revision = "0006_job_contacts"
down_revision = "0005_job_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE job_contacts (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            company VARCHAR(200) NOT NULL DEFAULT '',
            contact_name VARCHAR(120) NOT NULL,
            role VARCHAR(120) NOT NULL DEFAULT '',
            channel VARCHAR(100) NOT NULL DEFAULT '',
            contact_value VARCHAR(300) NOT NULL DEFAULT '',
            opportunity_id TEXT NOT NULL DEFAULT '',
            notes VARCHAR(2000) NOT NULL DEFAULT '',
            next_contact_date VARCHAR(10) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (length(trim(contact_name)) > 0)
        )
    """)
    op.execute("""
        CREATE INDEX ix_job_contacts_owner
        ON job_contacts (owner_id, updated_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_contacts")
