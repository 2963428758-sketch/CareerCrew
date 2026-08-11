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
    def get_by_ids(self, ids: list[str]) -> list[VectorRecord]: ...


def _matches(metadata: dict, filters: dict) -> bool:
    return all(metadata.get(k) == v for k, v in filters.items())


class FakeVectorStore(BaseVectorStore):
    """内存版向量库（cosine 相似度），单测复用，避免真实 Qdrant。"""

    def __init__(self, settings: Settings) -> None:
        self._records: dict[str, VectorRecord] = {}

    def upsert(self, records: list[VectorRecord]) -> None:
        for r in records:
            self._records[r.id] = r

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

    def get_by_ids(self, ids: list[str]) -> list[VectorRecord]:
        return [self._records[i] for i in ids if i in self._records]

    def count(self) -> int:
        return len(self._records)

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
