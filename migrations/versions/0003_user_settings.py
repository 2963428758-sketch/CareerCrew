"""用户个性化设置与自定义 API Key 存储表。

Revision ID: 0003_user_settings
Revises: 0002_long_term_memory_records
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0003_user_settings"
down_revision = "0002_long_term_memory_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # SQLAlchemy 2.x 要求 text() 包装；此前为裸字符串，在 SA2 下直接执行会抛
    # ObjectNotExecutableError，导致 0003 之后整条迁移链无法推进。
    bind.execute(
        text(
            """
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id TEXT PRIMARY KEY,
            settings JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS user_settings;"))
