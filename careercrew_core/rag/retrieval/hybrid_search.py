"""Hybrid 检索编排（D3）：BGE-M3 dense+sparse 召回 + Rerank。

query -> BGE-M3 encode(dense+sparse) -> MilvusStore.query(hybrid, Milvus 原生 RRF)
-> top_m 候选 -> rerank -> top_k 终。

自建 RRF（fusion.rrf_fuse）用于多路/多查询融合（M 阶段 Agentic RAG）；单路 hybrid
直接用 Milvus 原生 RRF（高效，避免双路分别召回的开销）。
"""
from __future__ import annotations

from careercrew_ai.embedding.base_embedding import BaseEmbedding
from careercrew_ai.reranker.base_reranker import BaseReranker
from careercrew_ai.vector_store.base_vector_store import BaseVectorStore, QueryResult


class HybridSearch:
    def __init__(
        self,
        embedding: BaseEmbedding,
        store: BaseVectorStore,
        reranker: BaseReranker | None = None,
        top_m: int = 30,
    ) -> None:
        self._embedding = embedding
        self._store = store
        self._reranker = reranker
        self._top_m = top_m

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[QueryResult]:
        # 1. 编码 query -> dense + sparse
        emb = self._embedding.encode([query])
        dense = emb.dense[0]
        sparse = emb.sparse[0] if emb.sparse else None
        # 2. hybrid 召回（Milvus 原生 dense+sparse RRF）-> top_m 候选
        candidates = self._store.query(dense, top_k=self._top_m, filters=filters, sparse=sparse)
        # 3. rerank -> top_k 终（无 reranker 或失败则原序截断）
        if self._reranker is not None:
            try:
                return self._reranker.rerank(query, candidates, top_k=top_k)
            except Exception:
                pass  # 回退原序
        return candidates[:top_k]
