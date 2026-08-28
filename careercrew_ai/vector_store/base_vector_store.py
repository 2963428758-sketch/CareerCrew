"""向量库抽象基类 + 工厂（A4 骨架）。

分层：careercrew_ai 最底层，不反向依赖 careercrew_core（Settings 仅 TYPE_CHECKING）。

向量库后端仅 Qdrant（create_vector_store 工厂路由，见 DEV_SPEC 3.5）。
A4 提供 FakeVectorStore（内存版 cosine，单测复用）验证工厂路由与契约。
契约对齐 DEV_SPEC 3.5.1：upsert / query / delete_by_metadata / get_by_ids。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings

ACCESS_USER_KEY = "__access_user"


def _matches(metadata: dict, filters: dict) -> bool:
    for k, v in filters.items():
        if k == ACCESS_USER_KEY:
            visible = (
                metadata.get("visibility") == "public"
                or metadata.get("owner_user_id") == v
            )
            if not visible:
                return False
            continue
        if metadata.get(k) != v:
            return False
    return True


@dataclass
class VectorRecord:
    """向量库 upsert 记录。"""

    id: str
    dense: list[float] | np.ndarray
    text: str = ""
    metadata: dict = field(default_factory=dict)
    sparse: dict[int, float] | None = None  # BGE-M3 sparse（hybrid upsert 用）


@dataclass
class QueryResult:
    """检索结果。"""

    id: str
    score: float
    text: str
    metadata: dict
    image_path: str = ""  # 多模态：命中页面/对象图（绝对路径）
    type: str = ""        # page | object
    page: int | None = None


class BaseVectorStore(ABC):
    """向量库契约（对齐 DEV_SPEC 3.5.1）。"""

    @abstractmethod
    def upsert(self, records: list[VectorRecord]) -> None: ...

    @abstractmethod
    def query(
        self,
        dense: list[float] | np.ndarray,
        top_k: int = 10,
        filters: dict | None = None,
        sparse: dict[int, float] | None = None,
    ) -> list[QueryResult]: ...

    @abstractmethod
    def delete_by_metadata(self, filters: dict) -> int: ...

    @abstractmethod
    def delete_by_ids(self, ids: list[str]) -> int: ...

    @abstractmethod
    def get_by_ids(
        self, ids: list[str], filters: dict | None = None,
    ) -> list[VectorRecord]: ...


class FakeVectorStore(BaseVectorStore):
    """内存版向量库（cosine 相似度），单测复用，避免真实 Qdrant。"""

    def __init__(self, settings: Settings) -> None:
        self._records: dict[tuple[str, str], VectorRecord] = {}

    def upsert(self, records: list[VectorRecord]) -> None:
        for r in records:
            owner = str((r.metadata or {}).get("owner_user_id")
                        or (r.metadata or {}).get("user_id") or "")
            self._records[(owner, r.id)] = r

    def query(self, dense, top_k=10, filters=None, sparse=None):
        q = np.asarray(dense, dtype=np.float32)
        qn = q / (np.linalg.norm(q) + 1e-9)
        scored: list[QueryResult] = []
        for r in self._records.values():
            if filters and not _matches(r.metadata, filters):
                continue
            v = np.asarray(r.dense, dtype=np.float32)
            vn = v / (np.linalg.norm(v) + 1e-9)
            score = float(np.dot(qn, vn))
            scored.append(QueryResult(id=r.id, score=score, text=r.text, metadata=r.metadata))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    def delete_by_metadata(self, filters: dict) -> int:
        to_del = [rid for rid, r in self._records.items() if _matches(r.metadata, filters)]
        for rid in to_del:
            del self._records[rid]
        return len(to_del)

    def delete_by_ids(self, ids: list[str]) -> int:
        wanted = set(ids)
        to_del = [key for key, record in self._records.items() if record.id in wanted]
        for key in to_del:
            del self._records[key]
        return len(to_del)

    def get_by_ids(self, ids: list[str], filters: dict | None = None) -> list[VectorRecord]:
        wanted = set(ids)
        return [
            r for r in self._records.values()
            if r.id in wanted and (not filters or _matches(r.metadata, filters))
        ]

    def count(self, filters: dict | None = None) -> int:
        return sum(
            1 for r in self._records.values()
            if not filters or _matches(r.metadata, filters)
        )

    def list_docs(self, limit: int = 1000, filters: dict | None = None) -> list[dict]:
        docs: dict[tuple, dict] = {}
        for record in self._records.values():
            if filters and not _matches(record.metadata, filters):
                continue
            doc = str(record.metadata.get("doc") or record.id)
            visibility = str(record.metadata.get("visibility", "private"))
            key = (doc, visibility)
            doc_name = record.metadata.get("doc_name") or record.metadata.get("title") or ""
            entry = docs.setdefault(key, {
                "doc": doc,
                "doc_name": doc_name,
                "title": doc_name,
                "source": record.metadata.get("source", ""),
                "points": 0,
                "category": record.metadata.get("category", ""),
                "visibility": visibility,
                "owner_user_id": str(record.metadata.get("owner_user_id", "")),
            })
            if doc_name and not entry.get("doc_name"):
                entry["doc_name"] = doc_name
                entry["title"] = doc_name
            entry["points"] += 1
            if len(docs) >= limit:
                break
        return list(docs.values())

    def set_payload_by_filter(self, payload: dict, filters: dict) -> int:
        count = 0
        for record in self._records.values():
            if filters and not _matches(record.metadata, filters):
                continue
            for k, v in payload.items():
                if v is None:
                    record.metadata.pop(k, None)
                else:
                    record.metadata[k] = v
            count += 1
        return count

    def metadata_exists(self, filters: dict) -> bool:
        return any(_matches(r.metadata, filters) for r in self._records.values())

    def query_routes(
        self,
        dense=None,
        sparse: dict[int, float] | None = None,
        top_m: int = 10,
        filters: dict | None = None,
    ) -> dict[str, list[QueryResult]]:
        """测试占位：仅 dense 路近似（sparse 复用 dense 结果）。"""
        out: dict[str, list[QueryResult]] = {}
        if dense is not None:
            out["text_dense"] = self.query(dense, top_k=top_m, filters=filters)
            if sparse is not None:
                out["text_sparse"] = out["text_dense"]
        return out


_VECTOR_STORE_REGISTRY: dict[str, type[BaseVectorStore]] = {"fake": FakeVectorStore}


def create_vector_store(settings: Settings) -> BaseVectorStore:
    """按 settings.vector_store.backend 路由到具体实现。"""
    backend = settings.vector_store.backend
    if backend == "fake":
        return FakeVectorStore(settings)
    if backend == "qdrant":
        from careercrew_ai.vector_store.qdrant_store import QdrantStore

        return QdrantStore(settings)
    raise NotImplementedError(
        f"vector_store backend '{backend}' 尚未实现（已实现: fake, qdrant）"
    )


def register_vector_store(backend: str, cls: type[BaseVectorStore]) -> None:
    _VECTOR_STORE_REGISTRY[backend] = cls
