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

from careercrew_ai.vector_store.base_vector_store import (
    ACCESS_USER_KEY,
    BaseVectorStore,
    QueryResult,
    VectorRecord,
)

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings

# Keep the tenant namespace stable: existing owner-scoped points must not be
# silently re-keyed.  Legacy/no-owner IDs use a separate UUIDv5 namespace so a
# legacy logical ID can never reproduce the same namespace/name input pair as
# an owner-scoped point (the old single-namespace encoding allowed that).
_QID_TENANT_NS = uuid.UUID("8b1e2f3a-4c5d-4e6f-8a9b-0c1d2e3f4a5b")
_QID_LEGACY_NS = uuid.UUID("bb7bb0e5-b634-4da0-8b97-6004cc3b01bd")
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
        self._cfg = cfg

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
            MultiVectorComparator,
            MultiVectorConfig,
            PayloadSchemaType,
            SparseVectorParams,
            VectorParams,
        )

        colbert_params: dict[str, VectorParams] = {}
        if getattr(self._cfg, "colbert_multivector", False):
            # M7：ColBERT token 矩阵原生 multivector（MAX_SIM 服务端精排）
            colbert_params["text_colbert"] = VectorParams(
                size=self._dim, distance=Distance.COSINE,
                multivector_config=MultiVectorConfig(comparator=MultiVectorComparator.MAX_SIM),
            )

        if self._client.collection_exists(self._collection):
            # 存量集合补加 text_colbert（旧点无该向量，需重新摄取才有精排数据）
            if colbert_params:
                try:
                    self._client.update_collection(
                        self._collection, vectors_config=colbert_params,
                    )
                except Exception:
                    pass  # 已存在/版本不支持等，忽略
            return
        vectors_config: dict[str, VectorParams] = {
            "text_dense": VectorParams(size=self._dim, distance=Distance.COSINE),
            **colbert_params,
        }
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=vectors_config,
            sparse_vectors_config={"text_sparse": SparseVectorParams()},
        )
        for field in ("doc", "type", "page", "source", "category", "user_id", "owner_user_id", "visibility", "image_path"):
            try:
                self._client.create_payload_index(
                    self._collection, field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass  # 索引已存在等，忽略

    # ── id 映射 ──

    @staticmethod
    def _to_qid(sid: str, user_id: str = "") -> str:
        # Qdrant's physical key must include the tenant while payload._id remains
        # the original domain id (for example e_001) used by EpisodicMemory.
        if not user_id:
            return str(uuid.uuid5(_QID_LEGACY_NS, sid))
        key = f"{len(user_id)}:{user_id}{sid}"
        return str(uuid.uuid5(_QID_TENANT_NS, key))

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
            MinShould,
        )

        if not filters:
            return None
        must = []
        access_should = None
        for k, v in filters.items():
            if k == ACCESS_USER_KEY:
                access_should = [
                    FieldCondition(key="visibility", match=MatchValue(value="public")),
                    FieldCondition(key="owner_user_id", match=MatchValue(value=str(v))),
                ]
                continue
            if isinstance(v, list):
                must.append(FieldCondition(key=k, match=MatchAny(any=list(v))))
            elif isinstance(v, (str, int, float, bool)):
                must.append(FieldCondition(key=k, match=MatchValue(value=v)))
        # 访问控制是强制约束。当访问条件与其它 must 条件（如 doc 白名单）同时存在时，
        # 若把访问条件放在 Filter.should（无 min_should），它会被 Qdrant 视为可选
        # （optional OR），等于访问控制被短路、只剩上游 resolve_mentions 兜底。
        # 因此：有其它 must 时把「public OR 本人 owner」作为嵌套 Filter（min_should=1）
        # 并入 must，保证它和 doc 白名单做 AND；仅有访问条件时保持原样走 should。
        if access_should:
            if must:
                must.append(Filter(
                    should=access_should,
                    min_should=MinShould(conditions=access_should, min_count=1),
                ))
            else:
                return Filter(must=must, should=access_should)
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
        use_mv = getattr(self._cfg, "colbert_multivector", False)
        points = []
        for r in records:
            vectors: dict[str, Any] = {"text_dense": self._to_list(r.dense)}
            if r.sparse:
                vectors["text_sparse"] = SparseVector(
                    indices=[int(k) for k in r.sparse.keys()],
                    values=[float(v) for v in r.sparse.values()],
                )
            metadata = dict(r.metadata or {})
            # M7：multivector 模式下 colbert 矩阵进命名向量（服务端 MAX_SIM），
            # 不再落入 payload（避免字符串化与双份存储）
            if use_mv:
                cb = metadata.pop("colbert", None)
                if cb:
                    try:
                        vectors["text_colbert"] = [
                            [float(x) for x in row] for row in cb
                        ]
                    except Exception:
                        pass  # 矩阵格式异常时跳过该路，dense/sparse 不受影响
            payload: dict[str, Any] = {"_id": r.id, "text": (r.text or "")[:8192]}
            for k, v in metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    payload[k] = v
                elif v is not None:
                    payload[k] = str(v)
            owner = str(payload.get("owner_user_id") or payload.get("user_id") or "")
            points.append(PointStruct(id=self._to_qid(r.id, owner), vector=vectors, payload=payload))
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

    def colbert_scores(
        self,
        query_matrix: list[list[float]],
        ids: list[str],
        filters: dict | None = None,
    ) -> dict[str, float]:
        """M7 multivector：对给定候选点做服务端 MAX_SIM 打分。

        query_matrix：查询的 token 级矩阵 (n_query_tokens, dim)。
        返回 {原始 id: score}；候选缺失/异常时该 id 无条目。
        """
        if not query_matrix or not ids:
            return {}
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        try:
            flt = self._filter_expr(filters)
            must = list(getattr(flt, "must", []) or []) if flt is not None else []
            must.append(FieldCondition(key="_id", match=MatchAny(any=list(ids))))
            res = self._client.query_points(
                self._collection,
                query=query_matrix,
                using="text_colbert",
                query_filter=Filter(must=must),
                limit=len(ids),
                with_payload=["_id"],
                with_vectors=False,
            )
        except Exception:
            # 集合无 text_colbert 向量路（legacy/未开启 multivector）等：优雅空结果
            return {}
        out: dict[str, float] = {}
        for h in res.points:
            sid = (h.payload or {}).get("_id")
            if sid:
                out[str(sid)] = float(h.score)
        return out

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

    def set_payload_by_filter(self, payload: dict, filters: dict) -> int:
        """按过滤条件更新 payload（值为 None 表示删除该键）；返回命中点数。"""
        from qdrant_client.models import PointIdsList

        flt = self._filter_expr(filters)
        if not flt:
            return 0
        qids: list[str] = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                self._collection, scroll_filter=flt, limit=1000,
                offset=offset, with_payload=False, with_vectors=False,
            )
            qids.extend(p.id for p in points)
            if offset is None or len(qids) > 10000:
                break
        if qids:
            self._client.set_payload(
                self._collection, payload=payload,
                points=PointIdsList(points=qids),
            )
        return len(qids)

    def get_by_ids(
        self, ids: list[str], filters: dict | None = None,
    ) -> list[VectorRecord]:
        if not ids:
            return []
        combined = {**(filters or {}), "_id": list(ids)}
        res = []
        offset = None
        while True:
            points, offset = self._client.scroll(
                self._collection,
                scroll_filter=self._filter_expr(combined),
                limit=1000,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            res.extend(points)
            if offset is None:
                break
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
                sparse = {int(i): float(v) for i, v in zip(indices, values, strict=False)}
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

    def count(self, filters: dict | None = None) -> int:
        return int(self._client.count(
            self._collection, count_filter=self._filter_expr(filters), exact=True,
        ).count)

    def list_docs(self, limit: int = 1000, filters: dict | None = None) -> list[dict]:
        """按 payload.doc 聚合列出已入库文档（知识库管理用）；同名单按 visibility 分开。"""
        docs: dict[tuple, dict] = {}
        offset = None
        while True:
            points, offset = self._client.scroll(
                self._collection, limit=1000, offset=offset,
                scroll_filter=self._filter_expr(filters),
                with_payload=True, with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                doc = payload.get("doc") or payload.get("_id", "")
                visibility = str(payload.get("visibility", "private"))
                key = (doc, visibility)
                entry = docs.setdefault(key, {
                    "doc": doc,
                    "source": payload.get("source", ""),
                    "points": 0,
                    "category": payload.get("category", ""),
                    "visibility": visibility,
                    "owner_user_id": str(payload.get("owner_user_id", "")),
                })
                entry["points"] += 1
            if offset is None or len(docs) >= limit:
                break
        return list(docs.values())

    def metadata_exists(self, filters: dict) -> bool:
        if not filters:
            return False
        points, _ = self._client.scroll(
            self._collection,
            scroll_filter=self._filter_expr(filters),
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return bool(points)

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
