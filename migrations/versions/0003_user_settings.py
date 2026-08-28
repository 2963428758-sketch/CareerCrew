"""用户个性化设置与自定义 API Key 存储表。

Revision ID: 0003_user_settings
Revises: 0002_long_term_memory_records
"""
from __future__ import annotations

from alembic import op

revision = "0003_user_settings"
down_revision = "0002_long_term_memory_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id TEXT PRIMARY KEY,
            settings JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute("DROP TABLE IF EXISTS user_settings;")
