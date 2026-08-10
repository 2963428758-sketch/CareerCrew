"""Qdrant 向量库后端（多模态 RAG 唯一后端，纯文本向量）。

所有 collection 统一 schema：text_dense(1024/COSINE) + text_sparse。
（原 ColQwen 视觉多向量路已移除，图片内容由 MinerU 抽取文本后走文本向量。）

设计决策（对齐 MULTIMODAL_RAG_SPEC R4/R5）：
- 服务端 RRF 禁用（无法按路加权），query() 契约路径与 query_routes() 均返回
  各路 top_m 原始结果，由调用方用客户端加权 rrf_fuse 融合。
- 字符串点 id 稳定映射为 UUID（Qdrant 只接受 uint64/UUID），原始 id 存 payload._id，
  对外接口（BaseVectorStore 契约）始终返回原始字符串 id。
- 幂等 upsert：同 id 覆盖，重灌不产生脏数据。

qdrant-client 在 __init__ 内 lazy import。
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from careercrew_ai.vector_store.base_vector_store import BaseVectorStore, QueryResult, VectorRecord

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings

_QID_NS = uuid.UUID("8b1e2f3a-4c5d-4e6f-8a9b-0c1d2e3f4a5b")
_RRF_K = 60
_PAYLOAD_RESERVED = {"text", "_id"}


class QdrantStore(BaseVectorStore):
    def __init__(
        self,
        settings: Settings,
        collection_name: str | None = None,
        dim: int = 1024,
    ) -> None:
        from qdrant_client import QdrantClient

        cfg = settings.vector_store
        self._collection = collection_name or cfg.collections["knowledge"]
        self._dim = dim

        url = (cfg.url or "").strip()
        if url == ":memory:":
            self._client = QdrantClient(":memory:")
        elif url:
            self._client = QdrantClient(url=url, api_key=cfg.api_key or None)
        else:
            # 无 url 时本地嵌入模式（开发/测试用）
            self._client = QdrantClient(":memory:")
        self._ensure_collection()

    # ── schema ──

    def _ensure_collection(self) -> None:
        from qdrant_client.models import (
            Distance,
            PayloadSchemaType,
            SparseVectorParams,
            VectorParams,
        )

        if self._client.collection_exists(self._collection):
            return
        vectors_config: dict[str, VectorParams] = {
            "text_dense": VectorParams(size=self._dim, distance=Distance.COSINE),
        }
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=vectors_config,
            sparse_vectors_config={"text_sparse": SparseVectorParams()},
        )
        for field in ("doc", "type", "page", "source"):
            try:
                self._client.create_payload_index(
                    self._collection, field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass  # 索引已存在等，忽略

    # ── id 映射 ──

    @staticmethod
    def _to_qid(sid: str) -> str:
        return str(uuid.uuid5(_QID_NS, sid))

    @staticmethod
    def _to_list(v: Any) -> list[float]:
        if hasattr(v, "tolist"):
            return v.tolist()
        return list(v)

    @staticmethod
    def _filter_expr(filters: dict | None):
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            MatchAny,
            MatchValue,
        )

        if not filters:
            return None
        must = []
        for k, v in filters.items():
            if isinstance(v, list):
                must.append(FieldCondition(key=k, match=MatchAny(any=list(v))))
            elif isinstance(v, (str, int, float, bool)):
                must.append(FieldCondition(key=k, match=MatchValue(value=v)))
        return Filter(must=must) if must else None

    @staticmethod
    def _to_result(hit) -> QueryResult:
        payload = hit.payload or {}
        meta = {k: v for k, v in payload.items() if k not in _PAYLOAD_RESERVED}
        return QueryResult(
            id=payload.get("_id", str(hit.id)),
            score=float(hit.score),
            text=payload.get("text", ""),
            metadata=meta,
            image_path=payload.get("image_path", ""),
            type=payload.get("type", ""),
            page=payload.get("page"),
        )

    # ── 契约实现 ──

    def upsert(self, records: list[VectorRecord]) -> None:
        from qdrant_client.models import PointStruct, SparseVector

        if not records:
            return
        points = []
        for r in records:
            vectors: dict[str, Any] = {"text_dense": self._to_list(r.dense)}
            if r.sparse:
                vectors["text_sparse"] = SparseVector(
                    indices=[int(k) for k in r.sparse.keys()],
                    values=[float(v) for v in r.sparse.values()],
                )
            payload: dict[str, Any] = {"_id": r.id, "text": (r.text or "")[:8192]}
            for k, v in (r.metadata or {}).items():
                if isinstance(v, (str, int, float, bool)):
                    payload[k] = v
                elif v is not None:
                    payload[k] = str(v)
            points.append(PointStruct(id=self._to_qid(r.id), vector=vectors, payload=payload))
        self._client.upsert(self._collection, points)

    def query(
        self,
        dense,
        top_k: int = 10,
        filters: dict | None = None,
        sparse: dict[int, float] | None = None,
    ) -> list[QueryResult]:
        routes = self.query_routes(dense=dense, sparse=sparse, top_m=top_k, filters=filters)
        ranked = [r for r in routes.values() if r]
        if not ranked:
            return []
        return self._rrf_fuse(ranked, top_k=top_k)

    def query_routes(
        self,
        dense=None,
        sparse: dict[int, float] | None = None,
        top_m: int = 10,
        filters: dict | None = None,
    ) -> dict[str, list[QueryResult]]:
        """两路原始召回（text_dense / text_sparse），不做服务端融合。"""
        from qdrant_client.models import SparseVector

        flt = self._filter_expr(filters)
        out: dict[str, list[QueryResult]] = {}
        if dense is not None:
            res = self._client.query_points(
                self._collection,
                query=self._to_list(dense), using="text_dense",
                query_filter=flt, limit=top_m, with_payload=True, with_vectors=False,
            )
            out["text_dense"] = [self._to_result(h) for h in res.points]
        if sparse:
            sv = SparseVector(
                indices=[int(k) for k in sparse.keys()],
                values=[float(v) for v in sparse.values()],
            )
            res = self._client.query_points(
                self._collection,
                query=sv, using="text_sparse",
                query_filter=flt, limit=top_m, with_payload=True, with_vectors=False,
            )
            out["text_sparse"] = [self._to_result(h) for h in res.points]
        return out

    def delete_by_metadata(self, filters: dict) -> int:
        from qdrant_client.models import PointIdsList

        flt = self._filter_expr(filters)
        if not flt:
            return 0
        qids: list[str] = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                self._collection, scroll_filter=flt, limit=1000,
                offset=offset, with_payload=True, with_vectors=False,
            )
            qids.extend(p.id for p in points)
            if offset is None:
                break
            if len(qids) > 10000:
                break
        if qids:
            self._client.delete(self._collection, points_selector=PointIdsList(points=qids))
        return len(qids)

    def get_by_ids(self, ids: list[str]) -> list[VectorRecord]:
        if not ids:
            return []
        qids = [self._to_qid(i) for i in ids]
        res = self._client.retrieve(self._collection, ids=qids, with_vectors=True)
        records = []
        for p in res:
            payload = p.payload or {}
            vec = p.vector or {}
            meta = {k: v for k, v in payload.items() if k not in _PAYLOAD_RESERVED}
            sparse_raw = vec.get("text_sparse")
            sparse = None
            if sparse_raw:
                indices = getattr(sparse_raw, "indices", None)
                values = getattr(sparse_raw, "values", None)
                if indices is None and isinstance(sparse_raw, dict):
                    indices = sparse_raw.get("indices", [])
                    values = sparse_raw.get("values", [])
                sparse = {int(i): float(v) for i, v in zip(indices, values)}
            records.append(
                VectorRecord(
                    id=payload.get("_id", str(p.id)),
                    dense=vec.get("text_dense"),
                    sparse=sparse,
                    text=payload.get("text", ""),
                    metadata=meta,
                )
            )
        return records

    def count(self) -> int:
        return int(self._client.count(self._collection, exact=True).count)

    def list_docs(self, limit: int = 1000) -> list[dict]:
        """按 payload.doc 聚合列出已入库文档（知识库管理用）。"""
        docs: dict[str, dict] = {}
        offset = None
        while True:
            points, offset = self._client.scroll(
                self._collection, limit=1000, offset=offset,
                with_payload=True, with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                doc = payload.get("doc") or payload.get("_id", "")
                entry = docs.setdefault(
                    doc, {"doc": doc, "source": payload.get("source", ""), "points": 0}
                )
                entry["points"] += 1
            if offset is None or len(docs) >= limit:
                break
        return list(docs.values())

    # ── 客户端 RRF（契约路径，等权重；加权融合由 MultimodalSearch 走 fusion.rrf_fuse）──

    @classmethod
    def _rrf_fuse(
        cls,
        ranked_lists: list[list[QueryResult]],
        top_k: int | None = None,
    ) -> list[QueryResult]:
        scores: dict[str, float] = {}
        meta: dict[str, QueryResult] = {}
        for ranked in ranked_lists:
            for rank, item in enumerate(ranked, start=1):
                scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (_RRF_K + rank)
                meta[item.id] = item
        ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        if top_k is not None:
            ordered = ordered[:top_k]
        return [meta[i] for i, _ in ordered]
