"""Rerank 编排（D3）：调 ai.reranker，None/失败回退原序。"""
from __future__ import annotations

from careercrew_ai.reranker.base_reranker import BaseReranker
from careercrew_ai.vector_store.base_vector_store import QueryResult


def rerank(
    reranker: BaseReranker | None,
    query: str,
    candidates: list[QueryResult],
    top_k: int | None = None,
) -> list[QueryResult]:
    """调 reranker 重排；None 或失败回退原序（对齐 DEV_SPEC 5.7）。"""
    if reranker is None:
        return candidates[:top_k] if top_k is not None else list(candidates)
    try:
        return reranker.rerank(query, candidates, top_k=top_k)
    except Exception:
        return candidates[:top_k] if top_k is not None else list(candidates)
