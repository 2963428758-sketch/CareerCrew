"""pg_pool.normalize_dsn：SQLAlchemy 方言 DSN → psycopg conninfo 归一化。

背景：docker-compose 向容器注入 `postgresql+psycopg://...`（Alembic/SQLAlchemy
方言写法），psycopg3 的 conninfo 解析不认识 `+driver` 后缀，直接连接会失败。
应用侧所有 psycopg 入口（池/直连/checkpointer）都必须兼容两种写法。
"""
from __future__ import annotations

import pytest

from careercrew_core.pg_pool import normalize_dsn


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 常规写法原样通过
        ("postgresql://u:p@localhost:5432/db", "postgresql://u:p@localhost:5432/db"),
        ("postgres://u:p@db:5432/careercrew", "postgres://u:p@db:5432/careercrew"),
        # SQLAlchemy 方言后缀被剥离
        (
            "postgresql+psycopg://careercrew:careercrew@postgres:5432/careercrew",
            "postgresql://careercrew:careercrew@postgres:5432/careercrew",
        ),
        (
            "postgresql+psycopg2://u:p@h/db",
            "postgresql://u:p@h/db",
        ),
        # 关键字/参数 DSN 不受影响
        ("host=localhost port=5432 dbname=cc user=u password=p", "host=localhost port=5432 dbname=cc user=u password=p"),
        ("", ""),
    ],
)
def test_normalize_dsn(raw, expected):
    assert normalize_dsn(raw) == expected


def test_normalize_dsn_keeps_query_string():
    raw = "postgresql+psycopg://u:p@h:5432/db?sslmode=require"
    assert normalize_dsn(raw) == "postgresql://u:p@h:5432/db?sslmode=require"


def test_shared_pool_receives_normalized_dsn(monkeypatch):
    """get_shared_pool 用归一后的 DSN 建池并做记忆化键（同源两种写法共享一个池）。"""
    import careercrew_core.pg_pool as pg_pool

    created: list[str] = []

    class FakePool:
        def __init__(self, dsn, **kwargs):
            created.append(dsn)
            self.dsn = dsn

        def close(self):
            pass

    fake_module = type("M", (), {"ConnectionPool": FakePool})
    monkeypatch.setitem(__import__("sys").modules, "psycopg_pool", fake_module)
    monkeypatch.setattr(pg_pool, "_pools", {})
    monkeypatch.setattr(pg_pool, "_dict_row", lambda: object)

    a = pg_pool.get_shared_pool("postgresql+psycopg://u:p@h/db")
    b = pg_pool.get_shared_pool("postgresql://u:p@h/db")
    assert a is b
    assert created == ["postgresql://u:p@h/db"]
