"""情景记忆 append-only JSONL + parentId 树（C2/C3）。

存储：data/transcripts/{user_id}/{thread_id}.jsonl，每行一个 MemoryEntry。
append-only：只增不改，保证可完整回放（轨迹级评估基础）。
parentId 树：每条指向父节点，会话构成树；rebuild_context 从叶子回溯到根 = 上下文。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from careercrew_core.memory.types import MemoryEntry, TreeNode


class EpisodicMemory:
    """append-only JSONL 情景记忆 + parentId 树。"""

    def __init__(self, transcript_path: str | Path) -> None:
        self.path = Path(transcript_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _read_all(self) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(MemoryEntry.model_validate_json(line))
        return entries

    def _next_id(self, entries: list[MemoryEntry]) -> str:
        return f"e_{len(entries) + 1:03d}"

    def write(self, entry: MemoryEntry) -> MemoryEntry:
        """append 一条；id/ts/parentId 缺省时自动填（parentId 默认接最新条目，构成链）。"""
        entries = self._read_all()
        if not entry.id:
            entry.id = self._next_id(entries)
        if not entry.ts:
            entry.ts = datetime.now(timezone.utc).isoformat()
        if entry.parentId is None and entries:
            entry.parentId = entries[-1].id  # 默认接最新条目
        with self.path.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")
        return entry

    def get(self, id: str) -> MemoryEntry | None:
        for e in self._read_all():
            if e.id == id:
                return e
        return None

    def children(self, id: str) -> list[MemoryEntry]:
        return [e for e in self._read_all() if e.parentId == id]

    def latest(self) -> MemoryEntry | None:
        entries = self._read_all()
        return entries[-1] if entries else None

    def rebuild_context(self, leaf_id: str) -> list[MemoryEntry]:
        """从叶子沿 parentId 回溯到根，返回 root -> leaf 时间序（C3）。"""
        by_id = {e.id: e for e in self._read_all()}
        chain: list[MemoryEntry] = []
        cur = by_id.get(leaf_id)
        seen: set[str] = set()
        while cur and cur.id not in seen:
            chain.append(cur)
            seen.add(cur.id)
            cur = by_id.get(cur.parentId) if cur.parentId else None
        return list(reversed(chain))  # root -> leaf

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
