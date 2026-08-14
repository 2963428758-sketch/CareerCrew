"""情景记忆 append-only 事件 + parentId 树（统一存 Postgres/FakeMemoryDb）。

存储：episodic_events 表（user_id + id 主键，thread_id 分会话）。
append-only：只增不改，保证可完整回放（轨迹级评估基础）。
parentId 树：每条指向父节点，会话构成树；rebuild_context 从叶子回溯到根 = 上下文。
对话历史（user_message/agent_response）不再写入 episodic，只由 checkpointer 保存；
本层只沉淀关键事件（面试/投递/offer/复盘/匹配等）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from careercrew_core.memory.db import MemoryDb
from careercrew_core.memory.types import MemoryEntry, TreeNode


def _entry_from_row(row: dict) -> MemoryEntry:
    content = row.get("content")
    # Postgres 把 str content 存成 {"text": ...}，读回时还原
    if isinstance(content, dict) and set(content) == {"text"}:
        content = content["text"]
    return MemoryEntry(
        id=row["id"],
        parentId=row.get("parent_id"),
        type=row["type"],
        ts=row.get("ts", ""),
        content=content,
    )


class EpisodicMemory:
    """情景记忆（Postgres/Fake 统一后端）+ parentId 树。"""

    def __init__(
        self,
        db: MemoryDb,
        user_id: str = "u_001",
        thread_id: str = "m1",
    ) -> None:
        self._db = db
        self.user_id = user_id
        self.thread_id = thread_id

    def write(self, entry: MemoryEntry, thread_id: str | None = None) -> MemoryEntry:
        """append 一条；id/ts/parentId 缺省时自动填（parentId 默认接本线程最新条目）。"""
        tid = thread_id or self.thread_id
        # 取 id → 取最新父节点 → 插入 三步必须在同一把锁内完成：
        # 多个会话并行写入时，若分开加锁，两个线程可能拿到同一个 MAX(id)+1，
        # 后插入者会 ON CONFLICT 覆盖前一条（内容串线程）。write_lock 与
        # PostgresMemoryDb 的 @_synchronized 共用同一 RLock。
        with self._db.write_lock:
            if not entry.id:
                entry.id = self._db.next_episodic_id(self.user_id)
            if not entry.ts:
                entry.ts = datetime.now(timezone.utc).isoformat()
            if entry.parentId is None:
                latest = self._db.latest_episodic(self.user_id, tid)
                if latest:
                    entry.parentId = latest["id"]
            self._db.insert_episodic(
                user_id=self.user_id,
                thread_id=tid,
                entry_id=entry.id,
                parent_id=entry.parentId,
                type=entry.type,
                content=entry.content,
                ts=entry.ts,
            )
            return entry

    def get(self, id: str) -> MemoryEntry | None:
        row = self._db.get_episodic(self.user_id, id)
        return _entry_from_row(row) if row else None

    def children(self, id: str) -> list[MemoryEntry]:
        return [_entry_from_row(r) for r in self._db.children_episodic(self.user_id, id)]

    def latest(self) -> MemoryEntry | None:
        row = self._db.latest_episodic(self.user_id, self.thread_id)
        return _entry_from_row(row) if row else None

    def rebuild_context(self, leaf_id: str) -> list[MemoryEntry]:
        """从叶子沿 parentId 回溯到根，返回 root -> leaf 时间序。"""
        return [_entry_from_row(r) for r in self._db.chain_episodic(self.user_id, leaf_id)]

    def build_tree(self) -> TreeNode | None:
        """构建完整树（返回根节点；多根返回第一个）。"""
        entries = self._read_all()
        if not entries:
            return None
        nodes = {e.id: TreeNode(entry=e) for e in entries}
        root: TreeNode | None = None
        for e in entries:
            if e.parentId and e.parentId in nodes:
                nodes[e.parentId].children.append(nodes[e.id])
            elif root is None:
                root = nodes[e.id]
        return root

    def list(self, type: str | None = None, limit: int | None = None) -> list[MemoryEntry]:
        """列出本用户（可限定本线程/类型）的情景事件。"""
        rows = self._db.list_episodic(
            self.user_id, thread_id=self.thread_id, type=type, limit=limit
        )
        return [_entry_from_row(r) for r in rows]

    def _read_all(self) -> list[MemoryEntry]:
        """兼容旧契约：读本用户本线程全部条目（runtime/business_eval 用）。"""
        return self.list()

    def delete(self, entry_id: str | None = None, type: str | None = None) -> int:
        """删除条目（仅条目本身；删线程用 ThreadStore/API 层）。"""
        return self._db.delete_episodic(
            self.user_id, entry_id=entry_id, thread_id=self.thread_id, type=type
        )
