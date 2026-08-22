"""共享 psycopg 连接池（进程级，按 DSN 复用）。

背景：此前三种 store 各自管理连接——conversation/auth 每操作新建连接（TCP + 认证开销），
memory 进程级单条长连接（断连无恢复、跨线程共用非线程安全）。统一改为从池借还：
- 池按 DSN 记忆化，同一 DSN 的三个 store 天然共享同一个池；
- 借出即用、退出归还；断坏连接由池负责重建（自动重连）；
- 每操作事务语义不变：`pool.connection()` 上下文退出时提交/回滚。

容量：min_size=1（空闲不占资源）、max_size=10、checkout 超时 30s。
"""
from __future__ import annotations

import threading
from typing import Any

_POOL_MIN = 1
_POOL_MAX = 10
_POOL_TIMEOUT_S = 30.0

_lock = threading.Lock()
_pools: dict[str, Any] = {}


def get_shared_pool(dsn: str):
    """按 DSN 返回进程级共享 ConnectionPool（惰性创建）。

    需要 psycopg_pool：pip install 'psycopg[binary]' 'psycopg-pool'。
    """
    with _lock:
        pool = _pools.get(dsn)
        if pool is not None:
            return pool
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as e:  # pragma: no cover - env 缺依赖时给可读错误
            raise RuntimeError(
                "连接池需要 psycopg_pool：pip install 'psycopg[binary]' 'psycopg-pool'"
            ) from e
        pool = ConnectionPool(
            dsn,
            kwargs={"row_factory": _dict_row(), "connect_timeout": 5},
            min_size=_POOL_MIN,
            max_size=_POOL_MAX,
            timeout=_POOL_TIMEOUT_S,
            name="careercrew-pg",
            open=True,
        )
        _pools[dsn] = pool
        return pool


def reset_shared_pools() -> None:
    """关闭并清空全部共享池（仅测试隔离用）。"""
    with _lock:
        for pool in _pools.values():
            try:
                pool.close()
            except Exception:
                pass
        _pools.clear()


def _dict_row():
    import psycopg.rows

    return psycopg.rows.dict_row
