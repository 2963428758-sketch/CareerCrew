"""LangGraph thread checkpointer 封装（B1）。

LangGraph thread 级短期状态持久化：进程重启可恢复。生产默认 Postgres
（PostgresSaver）；SQLite（WAL）保留作本地/测试；memory 后端供单测/快速运行。

实现要点：
- SQLite：check_same_thread=False + WAL（Pregel 跨线程访问）。
- Postgres：psycopg 连接 + PostgresSaver，DSN 来自 settings（DATABASE_URL）。
- lazy import：仅在调用时导入对应包，避免不需要 checkpointer 的测试/CI 强行依赖。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from careercrew_core.state.settings import Settings

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

_VALID_CHECKPOINT_BACKENDS = {"postgres", "sqlite", "memory"}


def tenant_thread_id(user_id: str, thread_id: str) -> str:
    """Return a collision-safe internal checkpoint id without changing public ids."""
    if not user_id or not thread_id:
        raise ValueError("user_id and thread_id are required for checkpoint isolation")
    # Length-prefixing is reversible and cannot collide even when public ids contain separators.
    return f"tenant:{len(user_id)}:{user_id}{thread_id}"


def tenant_checkpoint_config(
    user_id: str,
    thread_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy a LangGraph config and bind its internal thread id to the auth principal."""
    out = dict(config or {})
    configurable = dict(out.get("configurable") or {})
    configurable["thread_id"] = tenant_thread_id(user_id, thread_id)
    out["configurable"] = configurable
    return out


def get_checkpointer(settings: Settings) -> "BaseCheckpointSaver":
    """按 settings.supervisor.checkpointer.backend 创建 checkpointer（lazy import）。"""
    cfg = settings.supervisor.checkpointer
    backend = cfg.backend
    if backend == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver
        import psycopg

        dsn = cfg.url or settings.memory.postgres.dsn
        if not dsn:
            raise ValueError("checkpointer backend=postgres 需要 supervisor.checkpointer.url 或 memory.postgres.dsn")
        # autocommit=True：PostgresSaver.setup() 的 CREATE INDEX CONCURRENTLY
        # 不能在事务块内执行（官方示例同款用法）
        conn = psycopg.connect(dsn, autocommit=True)
        saver = PostgresSaver(conn)
        saver.setup()  # 建 checkpoints/writes 表
        return saver
    if backend == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3

        path = Path(cfg.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：Pregel 循环跨线程访问连接
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")  # 并发读不阻塞写
        saver = SqliteSaver(conn)
        saver.setup()  # 建表
        return saver
    if backend == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    raise NotImplementedError(
        f"checkpointer backend '{backend}' 尚未实现，应为 {sorted(_VALID_CHECKPOINT_BACKENDS)} 之一"
    )
