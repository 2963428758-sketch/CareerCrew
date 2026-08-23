"""情景记忆向量索引。

entry -> embed(BGE-M3) -> Qdrant(careercrew_episodic_v2)；query -> 检索 ->
回 episodic 取完整条目。metadata 带 user_id，检索按用户隔离（多用户共享 collection）。
"""
from __future__ import annotations

from careercrew_ai.embedding.base_embedding import BaseEmbedding
from careercrew_ai.vector_store.base_vector_store import BaseVectorStore, VectorRecord
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry


def _entry_text(entry: MemoryEntry) -> str:
    c = entry.content
    if isinstance(c, dict):
        return " ".join(str(v) for v in c.values())
    return str(c)


class VectorIndex:
    def __init__(
        self,
        embedding: BaseEmbedding,
        store: BaseVectorStore,
        episodic: EpisodicMemory,
        user_id: str,
    ) -> None:
        self._embedding = embedding
        self._store = store
        self._episodic = episodic
        self._user_id = user_id

    def index_entry(self, entry: MemoryEntry) -> None:
        text = _entry_text(entry)
        emb = self._embedding.encode([text])
        self._store.upsert([
            VectorRecord(
                id=entry.id, dense=emb.dense[0],
                sparse=emb.sparse[0] if emb.sparse else None,
                text=text, metadata={
                    "memory_id": entry.id,
                    "type": entry.type,
                    "user_id": self._user_id,
                    "thread_id": self._episodic.thread_id,
                },
            )
        ])

    def index_all(self) -> int:
        """把 episodic 里全部条目索引（幂等，upsert 覆盖）。返回条目数。"""
        n = 0
        for entry in self._episodic._read_all():
            self.index_entry(entry)
            n += 1
        return n

    def search(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        emb = self._embedding.encode([query])
        results = self._store.query(
            emb.dense[0], top_k=top_k,
            sparse=emb.sparse[0] if emb.sparse else None,
            filters={"user_id": self._user_id},
        )
        by_id = {entry.id: entry for entry in self._episodic._read_all()}
        # 按向量相关度返回，不能因回表扫描丢失结果排名。
        return [by_id[result.id] for result in results if result.id in by_id]
