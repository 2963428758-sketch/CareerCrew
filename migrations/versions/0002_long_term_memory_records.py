"""长期记忆可演进数据模型（不迁移普通聊天 transcript）。

Revision ID: 0002_long_term_memory_records
Revises: 0001_baseline
"""
from __future__ import annotations

from alembic import op

revision = "0002_long_term_memory_records"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增长期记忆 header、值、来源、血缘、向量 outbox 与运行观察表。

    旧 semantic_facts / episodic_events 在兼容期保留为读写适配层；本迁移不把
    user_message / agent_response 回填为长期记忆。
    """
    bind = op.get_bind()
    statements = [
        """
        CREATE TABLE IF NOT EXISTS memory_records (
            id UUID PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL,
            memory_type VARCHAR(20) NOT NULL CHECK (memory_type IN ('semantic', 'episodic')),
            category VARCHAR(100) NOT NULL,
            scope_type VARCHAR(20) NOT NULL DEFAULT 'global' CHECK (scope_type IN ('global', 'domain', 'agent')),
            scope_key VARCHAR(100),
            capture_mode VARCHAR(20) NOT NULL CHECK (capture_mode IN ('automatic', 'explicit', 'form', 'verified_event', 'consolidated', 'migration')),
            normalized_key VARCHAR(255),
            cardinality VARCHAR(20) NOT NULL DEFAULT 'single',
            canonical_hash VARCHAR(128),
            display_text TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            importance REAL NOT NULL DEFAULT 0.5,
            source_quality REAL NOT NULL DEFAULT 1.0,
            sensitivity VARCHAR(30) NOT NULL DEFAULT 'normal',
            lifecycle_class VARCHAR(30) NOT NULL DEFAULT 'long_lived',
            valid_from TIMESTAMPTZ,
            valid_until TIMESTAMPTZ,
            last_confirmed_at TIMESTAMPTZ,
            last_accessed_at TIMESTAMPTZ,
            access_count INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'expired', 'deleted', 'quarantined')),
            schema_version INTEGER NOT NULL DEFAULT 1,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_memory_records_active ON memory_records(user_id, status, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_memory_records_key ON memory_records(user_id, normalized_key, status)",
        """
        CREATE TABLE IF NOT EXISTS memory_semantic_values (
            memory_id UUID PRIMARY KEY REFERENCES memory_records(id) ON DELETE CASCADE,
            normalized_value JSONB NOT NULL,
            value_type VARCHAR(50), unit VARCHAR(50), locale VARCHAR(20), value_hash VARCHAR(128)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_episodic_events (
            memory_id UUID PRIMARY KEY REFERENCES memory_records(id) ON DELETE CASCADE,
            event_type VARCHAR(100) NOT NULL, occurred_at TIMESTAMPTZ NOT NULL,
            entity_type VARCHAR(100), entity_id VARCHAR(255), event_state VARCHAR(50),
            event_payload JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_sources (
            id UUID PRIMARY KEY, memory_id UUID NOT NULL REFERENCES memory_records(id) ON DELETE CASCADE,
            source_type VARCHAR(50) NOT NULL, conversation_id UUID, message_id UUID, turn_id UUID,
            run_id UUID, agent_id VARCHAR(100), tool_call_id UUID, source_excerpt_redacted TEXT,
            asserted_by VARCHAR(50), evidence_strength REAL NOT NULL DEFAULT 1.0,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_memory_sources_record ON memory_sources(memory_id, observed_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS memory_relations (
            id UUID PRIMARY KEY, from_memory_id UUID NOT NULL REFERENCES memory_records(id) ON DELETE CASCADE,
            to_memory_id UUID NOT NULL REFERENCES memory_records(id) ON DELETE CASCADE,
            relation_type VARCHAR(30) NOT NULL CHECK (relation_type IN ('supersedes', 'conflicts_with', 'supports', 'duplicate_of', 'derived_from', 'consolidates')),
            confidence REAL NOT NULL DEFAULT 1.0, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_memory_relations_from ON memory_relations(from_memory_id, relation_type)",
        """
        CREATE TABLE IF NOT EXISTS memory_vector_outbox (
            id UUID PRIMARY KEY, memory_id UUID, user_id VARCHAR(64) NOT NULL,
            operation VARCHAR(10) NOT NULL CHECK (operation IN ('upsert', 'delete')),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb, attempts INTEGER NOT NULL DEFAULT 0,
            available_at TIMESTAMPTZ NOT NULL DEFAULT now(), processed_at TIMESTAMPTZ,
            last_error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_memory_outbox_pending ON memory_vector_outbox(processed_at, available_at)",
        """
        CREATE TABLE IF NOT EXISTS agent_run_memory_traces (
            id UUID PRIMARY KEY, run_id UUID, user_id VARCHAR(64) NOT NULL,
            policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb, query_redacted TEXT,
            candidates JSONB NOT NULL DEFAULT '[]'::jsonb, skipped JSONB NOT NULL DEFAULT '[]'::jsonb,
            retrieved_memory_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            injected_memory_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            written_memory_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    ]
    for statement in statements:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "agent_run_memory_traces", "memory_vector_outbox", "memory_relations", "memory_sources",
        "memory_episodic_events", "memory_semantic_values", "memory_records",
    ):
        bind.exec_driver_sql(f"DROP TABLE IF EXISTS {table} CASCADE")
