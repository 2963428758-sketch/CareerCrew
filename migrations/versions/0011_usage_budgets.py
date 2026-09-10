"""账号级 Token/费用事件、预算策略与并发预留。

Revision ID: 0011_usage_budgets
Revises: 0010_knowledge_governance
"""
from __future__ import annotations

from alembic import op

revision: str = "0011_usage_budgets"
down_revision: str | None = "0010_knowledge_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_budgets (
            owner_id VARCHAR(64) NOT NULL,
            scope_type VARCHAR(20) NOT NULL CHECK (scope_type IN ('user', 'module')),
            scope_key VARCHAR(50) NOT NULL,
            period VARCHAR(20) NOT NULL CHECK (period IN ('daily', 'monthly')),
            token_limit BIGINT CHECK (token_limit IS NULL OR token_limit >= 0),
            cost_limit_usd NUMERIC(20, 8) CHECK (cost_limit_usd IS NULL OR cost_limit_usd >= 0),
            soft_limit_ratio REAL NOT NULL DEFAULT 0.8
                CHECK (soft_limit_ratio > 0 AND soft_limit_ratio <= 1),
            downgrade_model VARCHAR(150),
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (owner_id, scope_type, scope_key, period),
            CHECK (token_limit IS NOT NULL OR cost_limit_usd IS NOT NULL),
            CHECK ((scope_type = 'user' AND scope_key = '*') OR scope_type = 'module')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_reservations (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            module VARCHAR(50) NOT NULL,
            provider VARCHAR(80) NOT NULL,
            model VARCHAR(150) NOT NULL,
            estimated_tokens BIGINT NOT NULL CHECK (estimated_tokens >= 0),
            estimated_cost_usd NUMERIC(20, 8) CHECK (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0),
            status VARCHAR(20) NOT NULL DEFAULT 'reserved'
                CHECK (status IN ('reserved', 'settled', 'released')),
            source_request_id VARCHAR(128),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, source_request_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            module VARCHAR(50) NOT NULL,
            provider VARCHAR(80) NOT NULL,
            model VARCHAR(150) NOT NULL,
            input_tokens BIGINT CHECK (input_tokens IS NULL OR input_tokens >= 0),
            output_tokens BIGINT CHECK (output_tokens IS NULL OR output_tokens >= 0),
            total_tokens BIGINT CHECK (total_tokens IS NULL OR total_tokens >= 0),
            estimated_cost_usd NUMERIC(20, 8),
            pricing_version VARCHAR(80) NOT NULL,
            pricing_status VARCHAR(20) NOT NULL CHECK (pricing_status IN ('known', 'unknown')),
            status VARCHAR(20) NOT NULL CHECK (status IN ('completed', 'failed', 'cancelled', 'rejected')),
            reservation_id UUID REFERENCES usage_reservations(id) ON DELETE SET NULL,
            source_event_id VARCHAR(128),
            downgrade_reason VARCHAR(80),
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, source_event_id)
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_usage_events_owner_time ON usage_events(owner_id, occurred_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_usage_events_owner_module_time ON usage_events(owner_id, module, occurred_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_usage_reservations_owner_status_time ON usage_reservations(owner_id, status, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_usage_budgets_owner_enabled ON usage_budgets(owner_id, enabled, period)",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_events")
    op.execute("DROP TABLE IF EXISTS usage_reservations")
    op.execute("DROP TABLE IF EXISTS usage_budgets")
