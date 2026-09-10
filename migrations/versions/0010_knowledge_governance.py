"""知识库文档版本、分块索引状态和引用统计。

Revision ID: 0010_knowledge_governance
Revises: 0009_memory_governance

The legacy upload tables/files remain compatible.  These tables are the
durable governance layer used to publish a fully indexed version atomically,
retain failed versions for diagnosis, and count citations idempotently.
"""
from __future__ import annotations

from alembic import op

revision: str = "0010_knowledge_governance"
down_revision: str | None = "0009_memory_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_documents (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            name VARCHAR(255) NOT NULL CHECK (length(trim(name)) > 0),
            category VARCHAR(100) NOT NULL DEFAULT 'knowledge',
            visibility VARCHAR(20) NOT NULL DEFAULT 'private'
                CHECK (visibility IN ('private', 'public')),
            status VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'deleted', 'expired')),
            active_version_id UUID,
            expires_at TIMESTAMPTZ,
            credibility REAL NOT NULL DEFAULT 1.0
                CHECK (credibility >= 0 AND credibility <= 1),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_document_versions (
            id UUID PRIMARY KEY,
            document_id UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL CHECK (version_number > 0),
            content_sha256 CHAR(64) NOT NULL
                CHECK (content_sha256 ~ '^[0-9a-fA-F]{64}$'),
            size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
            mime_type VARCHAR(255) NOT NULL DEFAULT 'application/octet-stream',
            status VARCHAR(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'indexing', 'active', 'archived', 'failed', 'expired')),
            expires_at TIMESTAMPTZ,
            credibility REAL NOT NULL DEFAULT 1.0
                CHECK (credibility >= 0 AND credibility <= 1),
            indexed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (document_id, version_number),
            UNIQUE (document_id, content_sha256)
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'knowledge_documents_active_version_fk'
            ) THEN
                ALTER TABLE knowledge_documents
                    ADD CONSTRAINT knowledge_documents_active_version_fk
                    FOREIGN KEY (active_version_id)
                    REFERENCES knowledge_document_versions(id)
                    ON DELETE SET NULL;
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_document_chunks (
            id UUID PRIMARY KEY,
            version_id UUID NOT NULL REFERENCES knowledge_document_versions(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            page INTEGER CHECK (page IS NULL OR page > 0),
            text TEXT NOT NULL CHECK (length(trim(text)) > 0),
            text_hash CHAR(64) NOT NULL CHECK (text_hash ~ '^[0-9a-fA-F]{64}$'),
            index_status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (index_status IN ('pending', 'indexed', 'failed')),
            qdrant_point_id VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (version_id, ordinal)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_citation_events (
            id UUID PRIMARY KEY,
            owner_id VARCHAR(64) NOT NULL,
            document_id UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            version_id UUID NOT NULL REFERENCES knowledge_document_versions(id) ON DELETE CASCADE,
            chunk_id UUID NOT NULL REFERENCES knowledge_document_chunks(id) ON DELETE CASCADE,
            request_id VARCHAR(128) NOT NULL,
            count INTEGER NOT NULL DEFAULT 1 CHECK (count > 0),
            first_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, request_id, chunk_id)
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_knowledge_documents_owner_updated ON knowledge_documents(owner_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_documents_visibility_updated ON knowledge_documents(visibility, status, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_versions_document_status ON knowledge_document_versions(document_id, status, version_number DESC)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_version_ordinal ON knowledge_document_chunks(version_id, ordinal)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_citations_document ON knowledge_citation_events(document_id, version_id, chunk_id)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_citations_owner ON knowledge_citation_events(owner_id, last_at DESC)",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_citation_events")
    op.execute("DROP TABLE IF EXISTS knowledge_document_chunks")
    op.execute("DROP TABLE IF EXISTS knowledge_document_versions")
    op.execute("DROP TABLE IF EXISTS knowledge_documents")
