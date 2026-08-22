"""PG 集成测试：alembic baseline 与运行时惰性建表的 schema 一致性对比。

两个一次性库互相对照：
- src 库：实例化各 store 触发运行时惰性 DDL（conversation/auth/memory/jobs/attachments）
- dst 库：子进程跑 `alembic upgrade head`
逐列比对 information_schema.columns（类型/可空/默认值）与 p/u/f 约束集合，
防止「baseline 快照」与「代码内惰性 DDL」日后漂移。改了惰性 DDL 就该同步出新 migration。

缺 POSTGRES_TEST_DSN 跳过；拒绝指向生产库 careercrew。
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

DSN = os.environ.get("POSTGRES_TEST_DSN", "").strip()
REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set"),
]


def _require_disposable_db(dsn: str) -> None:
    dbname = urlparse(dsn.replace("postgresql://", "postgres://")).path.lstrip("/")
    if dbname == "careercrew":
        raise RuntimeError(
            "POSTGRES_TEST_DSN 指向生产库 careercrew，拒绝运行。请使用一次性测试库。"
        )


def _make_db(base_dsn: str, name: str) -> str:
    """建一次性库并返回同名 URL 形式 DSN（SQLAlchemy/alembic 需要 URL）。"""
    parts = conninfo_to_dict(base_dsn)
    admin = make_conninfo(**{**parts, "dbname": "postgres"})
    import psycopg

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {name} OWNER {parts.get('user', 'careercrew')}")
    return _swap_dbname(base_dsn, name)


def _swap_dbname(url_dsn: str, dbname: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    s = urlsplit(url_dsn.replace("postgresql://", "postgres://", 1))
    out = urlunsplit(("postgres", s.netloc, f"/{dbname}", s.query, ""))
    return out.replace("postgres://", "postgresql://", 1)


def _drop_db(base_dsn: str, name: str) -> None:
    parts = conninfo_to_dict(base_dsn)
    admin = make_conninfo(**{**parts, "dbname": "postgres"})
    import psycopg

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def _trigger_lazy_ddl(dsn: str) -> None:
    """在空库上触发全部运行时惰性 DDL（与各 store 生产首用路径一致）。"""
    from careercrew_api.auth.store import PostgresAccountStore
    from careercrew_core.conversation.attachments import PostgresAttachmentDb
    from careercrew_core.conversation.db import PostgresConversationDb
    from careercrew_core.jobs import PostgresJobsStore
    from careercrew_core.memory.db import PostgresMemoryDb

    PostgresConversationDb(dsn)._ensure()
    PostgresAccountStore(dsn)._ensure()
    PostgresMemoryDb(dsn).get_global_policy()
    PostgresJobsStore(dsn).search("warmup")
    PostgresAttachmentDb(dsn)._ensure()


def _run_alembic_upgrade(dsn: str) -> None:
    env = {**os.environ, "DATABASE_URL": dsn}
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"alembic upgrade 失败:\n{r.stdout}\n{r.stderr}"


def _schema_fingerprint(dsn: str) -> tuple:
    """(列指纹, 约束指纹)：排除 alembic 自身的版本表。"""
    import psycopg

    with psycopg.connect(dsn, row_factory=None) as conn:
        cols = conn.execute(
            "SELECT table_name, column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name <> 'alembic_version' "
            "ORDER BY table_name, column_name"
        ).fetchall()
        cons = conn.execute(
            "SELECT rel.relname, c.contype, c.conname, "
            "       (SELECT array_agg(a.attname ORDER BY a.attnum) "
            + "        FROM unnest(c.conkey) AS k "
            + "        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k) AS cols "
            + "FROM pg_constraint c JOIN pg_class rel ON rel.oid = c.conrelid "
            + "JOIN pg_namespace n ON n.oid = rel.relnamespace "
            + "WHERE n.nspname='public' AND rel.relname <> 'alembic_version' ORDER BY 1, 2, 3"
        ).fetchall()
    return (
        {(t, c, dt, nul, dft) for t, c, dt, nul, dft in cols},
        {(rel, typ, name, tuple(cols or [])) for rel, typ, name, cols in cons},
    )


def test_alembic_baseline_matches_lazy_ddl() -> None:
    _require_disposable_db(DSN)
    token = uuid.uuid4().hex[:8]
    src_name, dst_name = f"cc_cmp_src_{token}", f"cc_cmp_dst_{token}"
    src_dsn = dst_dsn = None
    try:
        src_dsn = _make_db(DSN, src_name)
        dst_dsn = _make_db(DSN, dst_name)

        _trigger_lazy_ddl(src_dsn)
        _run_alembic_upgrade(dst_dsn)

        src_cols, src_cons = _schema_fingerprint(src_dsn)
        dst_cols, dst_cons = _schema_fingerprint(dst_dsn)

        missing_in_baseline = src_cols - dst_cols
        extra_in_baseline = dst_cols - src_cols
        assert not missing_in_baseline, f"baseline 缺列（需出新 migration）: {sorted(missing_in_baseline)[:10]}"
        assert not extra_in_baseline, f"baseline 多列（快照过期）: {sorted(extra_in_baseline)[:10]}"
        assert src_cols == dst_cols, "列指纹不一致"

        assert src_cons == dst_cons, (
            "约束指纹不一致: "
            f"仅src={sorted(src_cons - dst_cons)[:5]} 仅dst={sorted(dst_cons - src_cons)[:5]}"
        )

        # 表数量一致（防某 store 漏触发）
        src_tables = {t for t, *_ in src_cols}
        assert len(src_tables) >= 20, f"触发面不足，仅 {len(src_tables)} 张表"
    finally:
        if src_dsn:
            _drop_db(DSN, src_name)
        if dst_dsn:
            _drop_db(DSN, dst_name)
