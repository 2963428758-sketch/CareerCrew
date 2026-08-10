"""多模态混合检索（R4）：文本路 -> 客户端加权 RRF -> VL 精排。

图片内容由 MinerU 抽取文本后统一走文本向量（无本地视觉模型）：
- 入库：MinerU 解析 -> 页面/对象文本 -> BGE-M3 dense+sparse
- 文本查询：BGE-M3 dense+sparse 两路召回
- 图片查询：image_reader 把查询图提取成文本（VLM API）后再走文本路

融合统一走客户端 ``fusion.rrf_fuse(weights=...)``（服务端 RRF 不支持加权，R4）。
"""
from __future__ import annotations

from typing import Callable

from careercrew_ai.embedding.base_embedding import BaseEmbedding
from careercrew_ai.reranker.base_reranker import BaseReranker
from careercrew_ai.vector_store.base_vector_store import BaseVectorStore, QueryResult
from careercrew_core.rag.retrieval.fusion import rrf_fuse


class MultimodalSearch:
    def __init__(
        self,
        embedding: BaseEmbedding,
        store: BaseVectorStore,
        reranker: BaseReranker | None = None,
        top_m: int = 30,
        image_reader: Callable[[str], str] | None = None,
    ) -> None:
        self._embedding = embedding
        self._store = store
        self._reranker = reranker
        self._top_m = top_m
        self._image_reader = image_reader

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict | None = None,
        image_path: str | None = None,
    ) -> list[QueryResult]:
        if image_path and self._image_reader is not None:
            try:
                extracted = self._image_reader(image_path).strip()
                query = f"{query}\n{extracted}" if query else extracted
            except Exception:
                pass  # 图片提取失败则回退原查询
        routes, weights = self._retrieve_routes(query, filters=filters)
        ranked = [r for r in routes if r]
        if not ranked:
            return []
        fused = rrf_fuse(ranked, top_k=self._top_m, weights=weights)
        if self._reranker is not None:
            try:
                return self._reranker.rerank(query, fused, top_k=top_k)
            except Exception:
                pass  # 精排失败回退 RRF 序
        return fused[:top_k]

    def _retrieve_routes(
        self,
        query: str,
        filters: dict | None = None,
    ) -> tuple[list[list[QueryResult]], list[float]]:
        dense = sparse = None
        if query:
            emb = self._embedding.encode([query])
            dense = emb.dense[0]
            sparse = emb.sparse[0] if emb.sparse else None
        route_map = self._store.query_routes(
            dense=dense, sparse=sparse, top_m=self._top_m, filters=filters,
        )
        ordered = [route_map.get("text_dense", []), route_map.get("text_sparse", [])]
        return ordered, [1.0, 1.0]
