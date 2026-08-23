"""共享 psycopg 连接池（进程级，按 DSN 复用）。

背景：此前三种 store 各自管理连接——conversation/auth 每操作新建连接（TCP + 认证开销），
memory 进程级单条长连接（断连无恢复、跨线程共用非线程安全）。统一改为从池借还：
- 池按 DSN 记忆化，同一 DSN 的三个 store 天然共享同一个池；
- 借出即用、退出归还；断坏连接由池负责重建（自动重连）；
- 每操作事务语义不变：`pool.connection()` 上下文退出时提交/回滚。

容量：min_size=1（空闲不占资源）、max_size=10、checkout 超时 30s；
可用环境变量 PG_POOL_MIN / PG_POOL_MAX / PG_POOL_TIMEOUT_S 覆盖。
"""
from __future__ import annotations

import os
import threading
from typing import Any

# 容量可经环境变量调整：auth/conversation/memory/attachment 四类 store 共享
# 同一进程级池，流式并发场景下默认 max=10 可能成为瓶颈（表现为 checkout 等
# 满 30s 后报错）。部署侧可按并发规模上调（如 PG_POOL_MAX=20）。
_POOL_MIN = max(int(os.environ.get("PG_POOL_MIN", "1")), 1)
_POOL_MAX = max(int(os.environ.get("PG_POOL_MAX", "10")), _POOL_MIN)
_POOL_TIMEOUT_S = max(float(os.environ.get("PG_POOL_TIMEOUT_S", "30")), 1.0)

_lock = threading.Lock()
_pools: dict[str, Any] = {}


def normalize_dsn(dsn: str) -> str:
    """把 SQLAlchemy 风格的方言 DSN 归一为 psycopg 可直接解析的形式。

    `postgresql+psycopg://...` 这类带驱动后缀的写法只有 SQLAlchemy/Alembic 认识
    （migrations/env.py 做映射）；psycopg3 的 conninfo 解析不认识 `+driver` 后缀，
    会直接连接失败。此处统一剥掉方言后缀，应用侧对两种写法都兼容——容器部署
    （docker-compose 注入 postgresql+psycopg://）与本地 .env（postgresql://）等价。
    """
    dsn = (dsn or "").strip()
    for sep in ("postgresql+", "postgres+"):
        idx = dsn.find(sep)
        if idx != -1:
            head = dsn[:idx + len(sep) - 1]  # 保留 "postgresql"/"postgres" 前缀
            tail = dsn[idx + len(sep):]
            # 只剥离紧随的字母数字驱动名（psycopg/psycopg2/asyncpg），不动其余内容
            driver = ""
            for ch in tail:
                if ch.isalnum():
                    driver += ch
                else:
                    break
            if driver:
                return head + tail[len(driver):]
            return dsn
    return dsn


def get_shared_pool(dsn: str):
    """按 DSN 返回进程级共享 ConnectionPool（惰性创建）。

    需要 psycopg_pool：pip install 'psycopg[binary]' 'psycopg-pool'。
    """
    dsn = normalize_dsn(dsn)
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
