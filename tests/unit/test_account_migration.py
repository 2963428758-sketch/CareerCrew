"""账号迁移计划逻辑：幂等、保留哈希、冲突检测。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import migrate_accounts_postgres as account_migration  # noqa: E402
from migrate_accounts_postgres import build_plan  # noqa: E402

PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$abc$def"

ADMIN = {
    "id": "u_001", "username": "liyou", "password_hash": PASSWORD_HASH,
    "role": "admin", "status": "active", "token_version": 0,
}


def test_plan_inserts_new_accounts():
    to_insert, conflicts = build_plan([ADMIN], [])
    assert to_insert == [ADMIN]
    assert conflicts == []


def test_plan_skips_identical_accounts():
    to_insert, conflicts = build_plan([ADMIN], [dict(ADMIN)])
    assert to_insert == [] and conflicts == []


def test_plan_reports_conflicting_accounts():
    changed = dict(ADMIN, role="user")
    to_insert, conflicts = build_plan([changed], [dict(ADMIN)])
    assert to_insert == []
    assert conflicts == [("u_001", "role")]


def test_sqlite_accounts_defaults_missing_columns(tmp_path):
    import sqlite3

    from migrate_accounts_postgres import sqlite_accounts

    db = tmp_path / "accounts.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE accounts (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, "
        "password_hash TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO accounts VALUES ('u_001', 'liyou', ?, 'admin', '2026-08-15T00:00:00+00:00')",
        (PASSWORD_HASH,),
    )
    conn.commit()
    conn.close()
    rows = sqlite_accounts(db)
    assert rows[0]["status"] == "active"
    assert rows[0]["token_version"] == 0
    assert rows[0]["password_hash"] == PASSWORD_HASH


def test_postgres_account_migration_normalizes_driver_dsn(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def transaction(self):
            return self

        def execute(self, *args, **kwargs):
            del args, kwargs
            return SimpleNamespace(fetchall=lambda: [])

    def connect(dsn: str, **kwargs):
        calls.append((dsn, kwargs))
        return FakeConnection()

    fake_psycopg = ModuleType("psycopg")
    fake_rows = ModuleType("psycopg.rows")
    fake_rows.dict_row = object()
    fake_psycopg.connect = connect
    fake_psycopg.rows = fake_rows
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.rows", fake_rows)

    dsn = "postgresql+psycopg://backup_user:secret@db.example:5433/careercrew"
    assert account_migration.apply_migration(dsn, [ADMIN]) == 1
    assert account_migration._pg_accounts(dsn) == []

    assert [item[0] for item in calls] == [
        "postgresql://backup_user:secret@db.example:5433/careercrew",
        "postgresql://backup_user:secret@db.example:5433/careercrew",
    ]
