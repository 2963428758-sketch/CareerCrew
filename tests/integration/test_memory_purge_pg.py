"""账号删除的长期记忆清理在真实 PostgreSQL 上的行为回归。

覆盖两点：没有治理审计时可以物理删除；存在 append-only 的治理事件时只能
软删记录并保留审计链（``memory_record_events`` 带 BEFORE UPDATE/DELETE 触发器）。
缺 ``POSTGRES_TEST_DSN`` 跳过；每次在一次性库上跑完整迁移。
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

DSN = os.environ.get("POSTGRES_TEST_DSN", "").strip()
REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set"),
]


def _swap_dbname(url_dsn: str, dbname: str) -> str:
    """把 URL 形式 DSN 的库名替换掉；alembic/SQLAlchemy 只接受 URL 形式。"""
    parts = urlsplit(url_dsn.replace("postgresql://", "postgres://", 1))
    swapped = urlunsplit(("postgres", parts.netloc, f"/{dbname}", parts.query, ""))
    return swapped.replace("postgres://", "postgresql://", 1)


def _disposable_dsn(base_dsn: str) -> tuple[str, str, str]:
    import psycopg

    name = f"cc_memory_purge_{uuid.uuid4().hex[:10]}"
    admin = _swap_dbname(base_dsn, "postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    return admin, _swap_dbname(base_dsn, name), name


def _drop_disposable(admin_dsn: str, name: str) -> None:
    import psycopg

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_purge_hard_deletes_without_audit_and_soft_deletes_with_audit() -> None:
    import psycopg

    from careercrew_core.memory.db import PostgresMemoryDb
    from careercrew_core.memory.records import BackfillItem, LongTermMemoryRepository

    admin, dsn, name = _disposable_dsn(DSN)
    try:
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(REPO_ROOT),
            env={**os.environ, "DATABASE_URL": dsn},
            capture_output=True,
            text=True,
        )
        assert upgrade.returncode == 0, upgrade.stderr[-800:]

        repository = LongTermMemoryRepository(PostgresMemoryDb(dsn))
        plain_user = f"u_plain_{uuid.uuid4().hex[:8]}"
        audited_user = f"u_audited_{uuid.uuid4().hex[:8]}"
        survivor = f"u_keep_{uuid.uuid4().hex[:8]}"

        def _item(user_id: str, key: str) -> BackfillItem:
            return BackfillItem(
                user_id=user_id,
                    memory_type="semantic",
                category="preference",
                normalized_key=key,
                display_text=f"{user_id} 的偏好",
                payload={"value": key},
                source_type="migration",
                legacy_id=key,
            )

        plain_record, _ = repository.upsert(_item(plain_user, "目标岗位"))
        audited_record, _ = repository.upsert(_item(audited_user, "期望城市"))
        survivor_record, _ = repository.upsert(_item(survivor, "期望薪资"))

        with psycopg.connect(dsn) as conn, conn.transaction():
            conn.execute(
                "INSERT INTO memory_record_events "
                "(id,owner_id,memory_id,action,reason,actor_id,row_version) "
                "VALUES (%s,%s,%s,'confirm','','tester',1)",
                (str(uuid.uuid4()), audited_user, audited_record["id"]),
            )

        plain_result = repository.delete_all_for_user(plain_user)
        audited_result = repository.delete_all_for_user(audited_user)

        with psycopg.connect(dsn) as conn:
            rows = {
                str(row[0]): row[1]
                for row in conn.execute("SELECT id, status FROM memory_records").fetchall()
            }
            events = conn.execute(
                "SELECT COUNT(*) FROM memory_record_events WHERE owner_id=%s",
                (audited_user,),
            ).fetchone()[0]
            outbox_owners = sorted(
                row[0]
                for row in conn.execute("SELECT user_id FROM memory_vector_outbox").fetchall()
            )

        plain_id = str(plain_record["id"])
        audited_id = str(audited_record["id"])
        survivor_id = str(survivor_record["id"])
        assert plain_result["records_deleted"] == 1
        assert plain_id not in rows
        assert audited_result["records_soft_deleted"] == 1
        assert rows[audited_id] == "deleted"
        assert events == 1, "治理审计必须保留"
        assert rows[survivor_id] == "active", "其他用户数据不得被波及"
        # 删除用户的行与队列都已清空；幸存用户的 outbox 行保留待索引。
        assert outbox_owners == [survivor]
    finally:
        _drop_disposable(admin, name)
