"""Milvus 向量库后端（D2）：BGE-M3 dense + sparse hybrid。

milvus-lite 嵌入式（零外部服务），原生支持 BGE-M3 hybrid 检索（DENSE + SPARSE + RRFRanker）。
metadata 用 dynamic field（可过滤）。pymilvus 在 __init__ 内 lazy import。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from careercrew_ai.vector_store.base_vector_store import BaseVectorStore, QueryResult, VectorRecord

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings


class MilvusStore(BaseVectorStore):
    def __init__(
        self,
        settings: Settings,
        collection_name: str | None = None,
        dim: int = 1024,
    ) -> None:
        from pymilvus import DataType, MilvusClient

        cfg = settings.vector_store
        path = Path(cfg.persist_path)
        path.mkdir(parents=True, exist_ok=True)
        db_file = path / "milvus_lite.db"
        self._collection = collection_name or cfg.collections["knowledge"]
        self._dim = dim
        self._client = MilvusClient(str(db_file))
        self._DataType = DataType
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if self._client.has_collection(self._collection):
            self._client.load_collection(self._collection)
            return
        DT = self._DataType
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("id", DT.VARCHAR, is_primary=True, max_length=128)
        schema.add_field("dense", DT.FLOAT_VECTOR, dim=self._dim)
        schema.add_field("sparse", DT.SPARSE_FLOAT_VECTOR)
        schema.add_field("text", DT.VARCHAR, max_length=8192)
        idx = self._client.prepare_index_params()
        idx.add_index(field_name="dense", index_type="FLAT", metric_type="COSINE")
        idx.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="IP")
        self._client.create_collection(self._collection, schema=schema, index_params=idx)
        self._client.load_collection(self._collection)

    @staticmethod
    def _to_list(v: Any) -> list[float]:
        if hasattr(v, "tolist"):
            return v.tolist()
        return list(v)

    def upsert(self, records: list[VectorRecord]) -> None:
        data = []
        for r in records:
            sparse = {int(k): float(v) for k, v in (r.sparse or {}).items()}
            row: dict = {
                "id": r.id,
                "dense": self._to_list(r.dense),
                "sparse": sparse,
                "text": (r.text or "")[:8192],
            }
            for k, v in (r.metadata or {}).items():
                # dynamic field；list/dict 转 JSON 字符串（Milvus dynamic 不支持复杂类型）
                row[k] = v if isinstance(v, (str, int, float, bool)) else str(v)
            data.append(row)
        self._client.upsert(self._collection, data)

    def query(self, dense, top_k=10, filters=None, sparse=None) -> list[QueryResult]:
        expr = self._filter_expr(filters)
        kwargs: dict = {"limit": top_k, "output_fields": ["text"]}
        if expr:
            kwargs["filter"] = expr
        if sparse:
            from pymilvus import AnnSearchRequest, RRFRanker

            dense_req = AnnSearchRequest(
                data=[self._to_list(dense)], anns_field="dense",
                param={"metric_type": "COSINE", "params": {}}, limit=top_k,
            )
            sparse_req = AnnSearchRequest(
                data=[sparse], anns_field="sparse",
                param={"metric_type": "IP", "params": {}}, limit=top_k,
            )
            res = self._client.hybrid_search(
                self._collection, [dense_req, sparse_req], RRFRanker(k=60), **kwargs,
            )
        else:
            res = self._client.search(
                self._collection, data=[self._to_list(dense)], anns_field="dense", **kwargs,
            )
        return self._to_query_results(res)

    def _to_query_results(self, res) -> list[QueryResult]:
        out: list[QueryResult] = []
        for hit in res[0]:
            entity = hit.get("entity", {}) or {}
            metadata = {k: v for k, v in entity.items() if k != "text"}
            out.append(
                QueryResult(
                    id=hit["id"],
                    score=float(hit["distance"]),
                    text=entity.get("text", ""),
                    metadata=metadata,
                )
            )
        return out

    def delete_by_metadata(self, filters: dict) -> int:
        expr = self._filter_expr(filters)
        if not expr:
            return 0
        res = self._client.query(self._collection, filter=expr, output_fields=["id"])
        ids = [r["id"] for r in res]
        if ids:
            self._client.delete(self._collection, ids=ids)
        return len(ids)

    def get_by_ids(self, ids: list[str]) -> list[VectorRecord]:
        if not ids:
            return []
        ids_lit = ",".join(f'"{i}"' for i in ids)
        res = self._client.query(
            self._collection, filter=f"id in [{ids_lit}]", output_fields=["text", "dense", "sparse"],
        )
        return [
            VectorRecord(
                id=r["id"], dense=r["dense"], text=r.get("text", ""),
                sparse=r.get("sparse"), metadata={},
            )
            for r in res
        ]

    def count(self) -> int:
        """当前 collection 实体数（demo / 工具判断是否已入库）。"""
        stats = self._client.get_collection_stats(self._collection)
        return int(stats.get("row_count", 0))

    @staticmethod
    def _filter_expr(filters: dict | None) -> str | None:
        if not filters:
            return None
        parts: list[str] = []
        for k, v in filters.items():
            if isinstance(v, str):
                parts.append(f'{k} == "{v}"')
            elif isinstance(v, bool):
                parts.append(f"{k} == {str(v).lower()}")
            elif isinstance(v, (int, float)):
                parts.append(f"{k} == {v}")
        return " and ".join(parts) if parts else None
