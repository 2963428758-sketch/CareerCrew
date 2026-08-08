"""SQLite checkpointer 封装（B1）。

LangGraph thread 级短期状态持久化：进程重启可恢复。默认 SQLite（WAL），
memory 后端供单测/快速运行。可替换为 Postgres（分布式，后期）。

实现要点：
- check_same_thread=False：LangGraph Pregel 循环跨线程访问连接，默认 sqlite 禁止跨线程。
- WAL：并发读不阻塞写。
- setup()：建 checkpoints/writes 表。
- lazy import langgraph_checkpoint_sqlite：仅在调用时导入，避免不需 checkpointer 的测试/CI 强行依赖该包。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from careercrew_core.state.settings import Settings

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

_VALID_CHECKPOINT_BACKENDS = {"sqlite", "memory"}


def get_checkpointer(settings: Settings) -> "BaseCheckpointSaver":
    """按 settings.supervisor.checkpointer.backend 创建 checkpointer（lazy import）。"""
    cfg = settings.supervisor.checkpointer
    backend = cfg.backend
    if backend == "sqlite":
        from langgraph_checkpoint_sqlite import SqliteSaver
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
