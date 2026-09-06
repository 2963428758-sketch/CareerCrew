"""Test-only SQL pool: execute real preparation queries without a network or DSN.

SQLite checks query effects, ownership, and cascades; it is not a PostgreSQL
dialect/concurrency integration test. Only psycopg parameter markers are adapted.
"""
import sqlite3
from contextlib import contextmanager


class SqlitePreparationPool:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = lambda cursor, row: dict(zip(
            [column[0] for column in cursor.description], row, strict=True))
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE preparation_opportunities (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                company TEXT NOT NULL, title TEXT NOT NULL, jd TEXT NOT NULL,
                city TEXT NOT NULL, salary TEXT NOT NULL, source TEXT NOT NULL, url TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (owner_id, id)
            );
            CREATE TABLE preparation_resume_versions (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, opportunity_id TEXT NOT NULL,
                label TEXT NOT NULL, content TEXT NOT NULL, original_content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (owner_id, opportunity_id, id),
                FOREIGN KEY (owner_id, opportunity_id)
                    REFERENCES preparation_opportunities (owner_id, id) ON DELETE CASCADE
            );
            CREATE TABLE preparation_sessions (
                thread_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, module TEXT NOT NULL,
                opportunity_id TEXT NOT NULL, resume_version_id TEXT NOT NULL,
                company TEXT NOT NULL, title TEXT NOT NULL, jd TEXT NOT NULL,
                resume_content TEXT NOT NULL, resume_label TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id, opportunity_id, resume_version_id)
                    REFERENCES preparation_resume_versions (owner_id, opportunity_id, id)
                    ON DELETE CASCADE
            );
        """)

    @contextmanager
    def connection(self):
        with self.db:
            yield self

    def execute(self, sql, params=()):
        return self.db.execute(sql.replace("%s", "?").replace("ILIKE", "LIKE"), params)

    def close(self):
        self.db.close()


class SqliteCareerPool(SqlitePreparationPool):
    """在准备库基础上叠加求职跟进域表（迁移 0005 的 SQLite 版本）。

    SQLite 不支持 ILIKE，执行前统一翻译为 LIKE；JSON 列以文本存储，
    读取侧由 store 的 _maybe_json 归一。"""
    def __init__(self):
        super().__init__()
        self.db.execute(
            "ALTER TABLE preparation_opportunities ADD COLUMN stage TEXT NOT NULL DEFAULT '待准备'")
        self.db.execute(
            "ALTER TABLE preparation_opportunities ADD COLUMN next_action TEXT NOT NULL DEFAULT ''")
        self.db.execute(
            "ALTER TABLE preparation_opportunities ADD COLUMN next_action_date TEXT NOT NULL DEFAULT ''")
        self.db.execute(
            "ALTER TABLE preparation_opportunities ADD COLUMN note TEXT NOT NULL DEFAULT ''")
        self.db.execute(
            "ALTER TABLE preparation_opportunities ADD COLUMN stage_updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")
        self.db.execute(
            "ALTER TABLE preparation_opportunities ADD COLUMN archived_at TEXT")
        self.db.executescript("""
            CREATE TABLE opportunity_stage_log (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, opportunity_id TEXT NOT NULL,
                from_stage TEXT NOT NULL, to_stage TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id, opportunity_id)
                    REFERENCES preparation_opportunities (owner_id, id) ON DELETE CASCADE
            );
            CREATE TABLE project_materials (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                name TEXT NOT NULL, background TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT '', actions TEXT NOT NULL DEFAULT '',
                results TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]',
                confirmed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE action_items (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                title TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
                due_date TEXT NOT NULL DEFAULT '', opportunity_id TEXT NOT NULL DEFAULT '',
                done INTEGER NOT NULL DEFAULT 0, done_at TEXT,
                postponed_count INTEGER NOT NULL DEFAULT 0, dismissed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE hr_followups (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                company TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '', content TEXT NOT NULL,
                received_at TEXT NOT NULL DEFAULT '', opportunity_id TEXT NOT NULL DEFAULT '',
                todo_note TEXT NOT NULL DEFAULT '', reply_draft TEXT NOT NULL DEFAULT '',
                draft_confirmed INTEGER NOT NULL DEFAULT 0, resolved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE offer_comparisons (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                company TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
                base_salary TEXT NOT NULL DEFAULT '', bonus TEXT NOT NULL DEFAULT '',
                equity TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
                work_mode TEXT NOT NULL DEFAULT '', growth TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '', opportunity_id TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE real_interview_records (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                company TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
                interview_date TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL DEFAULT '',
                questions TEXT NOT NULL DEFAULT '[]',
                overall_reflection TEXT NOT NULL DEFAULT '', weak_points TEXT NOT NULL DEFAULT '[]',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE interview_reports (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, thread_id TEXT NOT NULL,
                report TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE gap_analyses (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, opportunity_id TEXT NOT NULL,
                version_id TEXT NOT NULL DEFAULT '', result TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id, opportunity_id)
                    REFERENCES preparation_opportunities (owner_id, id) ON DELETE CASCADE
            );
            CREATE TABLE job_contacts (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                company TEXT NOT NULL DEFAULT '', contact_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL DEFAULT '',
                contact_value TEXT NOT NULL DEFAULT '', opportunity_id TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '', next_contact_date TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE career_profiles (
                owner_id TEXT PRIMARY KEY, stage TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '', goal TEXT NOT NULL DEFAULT '',
                onboarding_done INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
