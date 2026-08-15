"""真实 Postgres 迁移集成测试（缺 POSTGRES_TEST_DSN 跳过）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

DSN = os.environ.get("POSTGRES_TEST_DSN", "").strip()

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from migrate_accounts_postgres import apply_migration  # noqa: E402

pytestmark = pytest.mark.integration

pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set")


def _require_disposable_db(dsn: str) -> None:
    """安全闸：集成测试会清空 auth 表，只允许指向一次性测试库。"""
    from urllib.parse import urlparse

    dbname = urlparse(dsn.replace("postgresql://", "postgres://")).path.lstrip("/")
    if dbname == "careercrew":
        raise RuntimeError(
            "POSTGRES_TEST_DSN 指向生产库 careercrew，拒绝运行（会清空账号表）。"
            "请使用 careercrew_test 等一次性测试库。"
        )


@pytest.fixture
def clean_pg():
    import psycopg

    _require_disposable_db(DSN)
    with psycopg.connect(DSN) as conn, conn.transaction():
        conn.execute("DELETE FROM auth_refresh_sessions")
        conn.execute("DELETE FROM auth_accounts")
    yield
    with psycopg.connect(DSN) as conn, conn.transaction():
        conn.execute("DELETE FROM auth_refresh_sessions")
        conn.execute("DELETE FROM auth_accounts")


def test_apply_and_idempotent_rerun(clean_pg):
    row = {
        "id": "u_001", "username": "liyou", "password_hash": "$argon2id$fake",
        "role": "admin", "status": "active", "token_version": 0,
    }
    assert apply_migration(DSN, [row]) == 1
    assert apply_migration(DSN, [row]) == 1  # ON CONFLICT DO NOTHING 幂等
