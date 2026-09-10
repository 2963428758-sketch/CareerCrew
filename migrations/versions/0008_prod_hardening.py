"""生产化加固（第五期 P0）：上传任务持久化 + 分享令牌安全化。

- upload_tasks：简历/知识库上传任务落库（状态/进度/错误/结果/重试/租约/幂等键），
  重启不丢、多 worker 均可查询状态；执行仍在接收请求的进程内。
- career_share_tokens：令牌改为只存 SHA-256 哈希（原文仅在创建响应中出现一次），
  增加访问计数与最近访问时间（访问审计）；旧明文令牌在迁移中就地哈希后删除原文列。

Revision ID: 0008_prod_hardening
Revises: 0007_version_attribution_shares
"""
from alembic import op

revision = "0008_prod_hardening"
down_revision = "0007_version_attribution_shares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('''CREATE TABLE career_generation_events (
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, feature TEXT NOT NULL,
        source TEXT NOT NULL, fallback_reason TEXT, model TEXT, latency_ms INTEGER NOT NULL,
        input_tokens INTEGER, output_tokens INTEGER,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    op.execute('CREATE INDEX ix_generation_events_owner ON career_generation_events(owner_id, created_at)')
    op.execute('''CREATE TABLE career_product_events (
        id TEXT NOT NULL, owner_id TEXT NOT NULL, event TEXT NOT NULL,
        source TEXT NOT NULL, object_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (owner_id, id))''')
    op.execute('CREATE INDEX ix_product_events_owner ON career_product_events(owner_id, created_at)')
    # ── 上传任务持久化 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS upload_tasks (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'resume_parse',
            filename TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'done', 'error')),
            stage TEXT NOT NULL DEFAULT 'queued',
            progress REAL NOT NULL DEFAULT 0,
            error TEXT,
            result JSONB,
            attempts INTEGER NOT NULL DEFAULT 0,
            lease_expires_at TIMESTAMPTZ,
            idempotency_key TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_upload_tasks_owner
        ON upload_tasks (owner_id, created_at DESC)
    """)

    # ── 分享令牌安全化：原文 → SHA-256 哈希 + 访问审计 ──
    op.execute("ALTER TABLE career_share_tokens ADD COLUMN IF NOT EXISTS token_hash TEXT")
    op.execute("""
        UPDATE career_share_tokens
        SET token_hash = encode(sha256(token::bytea), 'hex')
        WHERE token_hash IS NULL AND token IS NOT NULL
    """)
    op.execute("DELETE FROM career_share_tokens WHERE token_hash IS NULL")
    op.execute("ALTER TABLE career_share_tokens ALTER COLUMN token_hash SET NOT NULL")
    op.execute("ALTER TABLE career_share_tokens DROP CONSTRAINT career_share_tokens_pkey")
    op.execute("ALTER TABLE career_share_tokens DROP COLUMN IF EXISTS token")
    op.execute("ALTER TABLE career_share_tokens ADD CONSTRAINT career_share_tokens_pkey PRIMARY KEY (token_hash)")
    op.execute("ALTER TABLE career_share_tokens ADD COLUMN IF NOT EXISTS access_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE career_share_tokens ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE career_share_tokens ALTER COLUMN mask_pii SET DEFAULT TRUE")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for table, columns in (
        ('preparation_opportunities', ('company', 'title', 'jd')),
        ('project_materials', ('name', 'background', 'results')),
        ('real_interview_records', ('company', 'title', 'overall_reflection')),
        ('offer_comparisons', ('company', 'title', 'notes')),
        ('action_items', ('title', 'note')),
    ):
        for column in columns:
            op.execute(f'CREATE INDEX IF NOT EXISTS ix_p5_{table}_{column} ON {table} USING gin ({column} gin_trgm_ops)')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS career_generation_events')
    op.execute('DROP TABLE IF EXISTS career_product_events')
    op.execute("DROP TABLE IF EXISTS upload_tasks")
    # Existing hashes must never become valid bearer credentials after rollback.
    op.execute("UPDATE career_share_tokens SET revoked_at = CURRENT_TIMESTAMP")
    op.execute("ALTER TABLE career_share_tokens DROP CONSTRAINT career_share_tokens_pkey")
    op.execute("ALTER TABLE career_share_tokens ADD COLUMN IF NOT EXISTS token TEXT")
    op.execute("UPDATE career_share_tokens SET token = token_hash WHERE token = '' OR token IS NULL")
    op.execute("ALTER TABLE career_share_tokens ALTER COLUMN token SET NOT NULL")
    op.execute("ALTER TABLE career_share_tokens DROP COLUMN IF EXISTS token_hash")
    op.execute("ALTER TABLE career_share_tokens DROP COLUMN IF EXISTS access_count")
    op.execute("ALTER TABLE career_share_tokens DROP COLUMN IF EXISTS last_accessed_at")
    op.execute("ALTER TABLE career_share_tokens ADD PRIMARY KEY (token)")
    op.execute("ALTER TABLE career_share_tokens ALTER COLUMN mask_pii SET DEFAULT FALSE")
    for table, columns in (
        ('preparation_opportunities', ('company', 'title', 'jd')),
        ('project_materials', ('name', 'background', 'results')),
        ('real_interview_records', ('company', 'title', 'overall_reflection')),
        ('offer_comparisons', ('company', 'title', 'notes')),
        ('action_items', ('title', 'note')),
    ):
        for column in columns:
            op.execute(f'DROP INDEX IF EXISTS ix_p5_{table}_{column}')
