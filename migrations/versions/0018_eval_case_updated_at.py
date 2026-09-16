"""Persist the timestamp written by evaluation-case edits."""
from alembic import op

revision = "0018_eval_case_updated_at"
down_revision = "0017_knowledge_source_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE eval_cases ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE eval_cases DROP COLUMN updated_at")
