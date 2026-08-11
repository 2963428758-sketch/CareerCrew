"""情景记忆向量索引（I1）。

entry -> embed(BGE-M3) -> Qdrant(careercrew_episodic)；query -> 检索 -> 回 episodic 取完整条目。
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
    ) -> None:
        self._embedding = embedding
        self._store = store
        self._episodic = episodic

    def index_entry(self, entry: MemoryEntry) -> None:
        text = _entry_text(entry)
        emb = self._embedding.encode([text])
        self._store.upsert([
            VectorRecord(
                id=entry.id, dense=emb.dense[0],
                sparse=emb.sparse[0] if emb.sparse else None,
                text=text, metadata={"type": entry.type},
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
            emb.dense[0], top_k=top_k, sparse=emb.sparse[0] if emb.sparse else None
        )
        hit_ids = {r.id for r in results}
        return [e for e in self._episodic._read_all() if e.id in hit_ids]
