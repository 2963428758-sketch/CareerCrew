"""Chroma 兜底向量库（D5）：dense-only（不支持 sparse hybrid）。

Milvus 不可用时兜底（ADR-7）。dense 检索即可用，sparse/hybrid 降级为 dense。
chromadb 在 __init__ 内 lazy import。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from careercrew_ai.vector_store.base_vector_store import BaseVectorStore, QueryResult, VectorRecord

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings


class ChromaStore(BaseVectorStore):
    def __init__(
        self,
        settings: Settings,
        collection_name: str | None = None,
        dim: int = 1024,  # Chroma 不固定 dim（首次 upsert 推断），保留接口一致
    ) -> None:
        import chromadb

        cfg = settings.vector_store
        path = Path(cfg.persist_path) / "chroma"
        path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(str(path))
        self._collection = self._client.get_or_create_collection(
            collection_name or cfg.collections["knowledge"]
        )

    @staticmethod
    def _to_list(v: Any) -> list[float]:
        if hasattr(v, "tolist"):
            return v.tolist()
        return list(v)

    @staticmethod
    def _sanitize_meta(meta: dict | None) -> dict:
        # Chroma metadata 只支持 str/int/float/bool
        out: dict = {}
        for k, v in (meta or {}).items():
            if isinstance(v, (str, int, float, bool)):
                out[k] = v
            elif v is not None:
                out[k] = str(v)
        return out

    @staticmethod
    def _where(filters: dict | None) -> dict | None:
        if not filters:
            return None
        w = {k: v for k, v in filters.items() if isinstance(v, (str, int, float, bool))}
        return w or None

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        self._collection.upsert(
            ids=[r.id for r in records],
            embeddings=[self._to_list(r.dense) for r in records],
            documents=[r.text or "" for r in records],
            metadatas=[self._sanitize_meta(r.metadata) for r in records],
        )

    def query(self, dense, top_k=10, filters=None, sparse=None) -> list[QueryResult]:
        # sparse 忽略（dense-only 兜底）
        kwargs: dict = {"query_embeddings": [self._to_list(dense)], "n_results": top_k}
        where = self._where(filters)
        if where:
            kwargs["where"] = where
        res = self._collection.query(**kwargs)
        out: list[QueryResult] = []
        for i, d, doc, meta in zip(
            res["ids"][0], res["distances"][0], res["documents"][0], res["metadatas"][0]
        ):
            out.append(QueryResult(id=i, score=float(d), text=doc, metadata=meta))
        return out

    def delete_by_metadata(self, filters: dict) -> int:
        where = self._where(filters)
        if not where:
            return 0
        res = self._collection.get(where=where)
        ids = res["ids"]
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def get_by_ids(self, ids: list[str]) -> list[VectorRecord]:
        if not ids:
            return []
        res = self._collection.get(ids=ids, include=["embeddings", "documents", "metadatas"])
        return [
            VectorRecord(id=i, dense=e, text=d, metadata=m)
            for i, e, d, m in zip(
                res["ids"], res.get("embeddings", []), res["documents"], res["metadatas"]
            )
        ]
