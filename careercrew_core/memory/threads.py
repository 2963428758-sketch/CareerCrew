"""会话线程元数据（title/module/pinned），替代从 JSONL 文件名推导。"""
from __future__ import annotations

from careercrew_core.memory.db import MemoryDb


class ThreadStore:
    def __init__(self, db: MemoryDb, user_id: str = "u_001") -> None:
        self._db = db
        self.user_id = user_id

    def upsert(
        self,
        thread_id: str,
        title: str = "",
        module: str = "chat",
        pinned: bool = False,
    ) -> dict:
        return self._db.upsert_thread(
            self.user_id, thread_id, title or "", module or "chat", bool(pinned)
        )

    def get(self, thread_id: str) -> dict | None:
        return self._db.get_thread(self.user_id, thread_id)

    def list(self, module: str | None = None) -> list[dict]:
        return self._db.list_threads(self.user_id, module=module)

    def delete(self, thread_id: str) -> int:
        return self._db.delete_thread(self.user_id, thread_id)

    def delete_all_for_thread(self, thread_id: str) -> int:
        """删除线程：情景事件 + 线程元数据。"""
        n_events = self._db.delete_episodic(self.user_id, thread_id=thread_id)
        n_thread = self.delete(thread_id)
        return n_events + n_thread
