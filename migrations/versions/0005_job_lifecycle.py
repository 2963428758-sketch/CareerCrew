"""求职持续跟进域：看板状态与变更记录、素材库、行动任务、HR 跟进、Offer 对比、
真实面试复盘、用户求职画像。所有行 owner 隔离；岗位级表以 (owner_id, opportunity_id)
复合键引用岗位，随岗位级联删除。

Revision ID: 0005_job_lifecycle
Revises: 0004_job_preparation
"""
from alembic import op

revision = "0005_job_lifecycle"
down_revision = "0004_job_preparation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 看板：岗位推进状态直接挂在岗位行上（一行一岗位） ──
    op.execute("""
        ALTER TABLE preparation_opportunities
            ADD COLUMN IF NOT EXISTS stage VARCHAR(20) NOT NULL DEFAULT '待准备',
            ADD COLUMN IF NOT EXISTS next_action VARCHAR(500) NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS next_action_date VARCHAR(10) NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS note VARCHAR(2000) NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS stage_updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ
    """)
    op.execute("DROP INDEX IF EXISTS ix_preparation_opportunities_stage")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_preparation_opportunities_stage
        ON preparation_opportunities (owner_id, stage, updated_at DESC)
    """)
    op.execute("""
        CREATE TABLE opportunity_stage_log (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, opportunity_id TEXT NOT NULL,
            from_stage VARCHAR(20) NOT NULL, to_stage VARCHAR(20) NOT NULL,
            note VARCHAR(500) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (owner_id, opportunity_id)
                REFERENCES preparation_opportunities (owner_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE INDEX ix_opportunity_stage_log_owner_opp
        ON opportunity_stage_log (owner_id, opportunity_id, created_at DESC)
    """)

    # ── 项目经历素材库 ──
    op.execute("""
        CREATE TABLE project_materials (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            name VARCHAR(200) NOT NULL CHECK (length(trim(name)) > 0),
            background TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT '',
            actions TEXT NOT NULL DEFAULT '',
            results TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            confirmed BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX ix_project_materials_owner
        ON project_materials (owner_id, updated_at DESC)
    """)

    # ── 行动计划与提醒 ──
    op.execute("""
        CREATE TABLE action_items (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            title VARCHAR(300) NOT NULL CHECK (length(trim(title)) > 0),
            note VARCHAR(1000) NOT NULL DEFAULT '',
            due_date VARCHAR(10) NOT NULL DEFAULT '',
            opportunity_id TEXT NOT NULL DEFAULT '',
            done BOOLEAN NOT NULL DEFAULT FALSE,
            done_at TIMESTAMPTZ,
            postponed_count INTEGER NOT NULL DEFAULT 0,
            dismissed BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX ix_action_items_owner_due
        ON action_items (owner_id, done, due_date)
    """)

    # ── HR 沟通与跟进 ──
    op.execute("""
        CREATE TABLE hr_followups (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            company VARCHAR(200) NOT NULL CHECK (length(trim(company)) > 0),
            title VARCHAR(200) NOT NULL DEFAULT '',
            channel VARCHAR(100) NOT NULL DEFAULT '',
            content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 20000),
            received_at VARCHAR(20) NOT NULL DEFAULT '',
            opportunity_id TEXT NOT NULL DEFAULT '',
            todo_note VARCHAR(1000) NOT NULL DEFAULT '',
            reply_draft TEXT NOT NULL DEFAULT '',
            draft_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
            resolved BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX ix_hr_followups_owner
        ON hr_followups (owner_id, resolved, updated_at DESC)
    """)

    # ── Offer 对比 ──
    op.execute("""
        CREATE TABLE offer_comparisons (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            company VARCHAR(200) NOT NULL CHECK (length(trim(company)) > 0),
            title VARCHAR(200) NOT NULL DEFAULT '',
            base_salary VARCHAR(200) NOT NULL DEFAULT '',
            bonus VARCHAR(200) NOT NULL DEFAULT '',
            equity VARCHAR(200) NOT NULL DEFAULT '',
            location VARCHAR(200) NOT NULL DEFAULT '',
            work_mode VARCHAR(200) NOT NULL DEFAULT '',
            growth TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            opportunity_id TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX ix_offer_comparisons_owner
        ON offer_comparisons (owner_id, updated_at DESC)
    """)

    # ── 真实面试复盘录入 ──
    op.execute("""
        CREATE TABLE real_interview_records (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            company VARCHAR(200) NOT NULL CHECK (length(trim(company)) > 0),
            title VARCHAR(200) NOT NULL DEFAULT '',
            interview_date VARCHAR(10) NOT NULL DEFAULT '',
            stage VARCHAR(100) NOT NULL DEFAULT '',
            questions JSONB NOT NULL DEFAULT '[]'::jsonb,
            overall_reflection TEXT NOT NULL DEFAULT '',
            weak_points JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX ix_real_interview_records_owner
        ON real_interview_records (owner_id, interview_date DESC)
    """)

    # ── 整场面试复盘报告（按准备会话/面试线程） ──
    op.execute("""
        CREATE TABLE interview_reports (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            report JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, thread_id, created_at)
        )
    """)
    op.execute("""
        CREATE INDEX ix_interview_reports_owner_thread
        ON interview_reports (owner_id, thread_id, created_at DESC)
    """)

    # ── 可解释岗位匹配分析（要求→证据→缺口） ──
    op.execute("""
        CREATE TABLE gap_analyses (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            opportunity_id TEXT NOT NULL,
            version_id TEXT NOT NULL DEFAULT '',
            result JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (owner_id, opportunity_id)
                REFERENCES preparation_opportunities (owner_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE INDEX ix_gap_analyses_owner_opp
        ON gap_analyses (owner_id, opportunity_id, created_at DESC)
    """)

    # ── 用户求职画像（首次使用引导 + 长期偏好；与账号同生命周期） ──
    op.execute("""
        CREATE TABLE career_profiles (
            owner_id TEXT PRIMARY KEY,
            stage VARCHAR(100) NOT NULL DEFAULT '',
            city VARCHAR(100) NOT NULL DEFAULT '',
            goal VARCHAR(1000) NOT NULL DEFAULT '',
            onboarding_done BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS career_profiles")
    op.execute("DROP TABLE IF EXISTS gap_analyses")
    op.execute("DROP TABLE IF EXISTS interview_reports")
    op.execute("DROP TABLE IF EXISTS real_interview_records")
    op.execute("DROP TABLE IF EXISTS offer_comparisons")
    op.execute("DROP TABLE IF EXISTS hr_followups")
    op.execute("DROP TABLE IF EXISTS action_items")
    op.execute("DROP TABLE IF EXISTS project_materials")
    op.execute("DROP TABLE IF EXISTS opportunity_stage_log")
    op.execute("ALTER TABLE preparation_opportunities DROP COLUMN IF EXISTS stage")
    op.execute("ALTER TABLE preparation_opportunities DROP COLUMN IF EXISTS next_action")
    op.execute("ALTER TABLE preparation_opportunities DROP COLUMN IF EXISTS next_action_date")
    op.execute("ALTER TABLE preparation_opportunities DROP COLUMN IF EXISTS note")
    op.execute("ALTER TABLE preparation_opportunities DROP COLUMN IF EXISTS stage_updated_at")
    op.execute("ALTER TABLE preparation_opportunities DROP COLUMN IF EXISTS archived_at")
