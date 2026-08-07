"""RRF 融合（D3）：Reciprocal Rank Fusion。

用排名倒数 1/(k+rank) 而非分数，避免不同检索器分数量纲不一致的问题。
多路 ranked 结果按 id 累加 RRF 分，重新排序。
"""
from __future__ import annotations

from careercrew_ai.vector_store.base_vector_store import QueryResult


def rrf_fuse(
    ranked_lists: list[list[QueryResult]],
    k: int = 60,
    top_k: int | None = None,
) -> list[QueryResult]:
    """多路 ranked 结果 RRF 融合。rank 为 1-based。"""
    scores: dict[str, float] = {}
    meta: dict[str, QueryResult] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (k + rank)
            meta[item.id] = item
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if top_k is not None:
        ordered = ordered[:top_k]
    return [
        QueryResult(id=i, score=s, text=meta[i].text, metadata=meta[i].metadata)
        for i, s in ordered
    ]
