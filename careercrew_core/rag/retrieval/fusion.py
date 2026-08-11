"""RRF 融合（D3 + R4）：Reciprocal Rank Fusion。

用排名倒数 1/(k+rank) 而非分数，避免不同检索器分数量纲不一致的问题。
多路 ranked 结果按 id 累加 RRF 分，重新排序。weights 支持按路加权
（默认等权，与旧行为完全一致；图片查询先经 VLM 提取文本并入文本路，
检索无独立 visual 路，故当前恒等权）。
"""
from __future__ import annotations

from dataclasses import replace

from careercrew_ai.vector_store.base_vector_store import QueryResult


def rrf_fuse(
    ranked_lists: list[list[QueryResult]],
    k: int = 60,
    top_k: int | None = None,
    weights: list[float] | None = None,
) -> list[QueryResult]:
    """多路 ranked 结果 RRF 融合。rank 为 1-based。

    weights: 与 ranked_lists 位置对齐的路权重；未提供时全部等权（旧行为不变）。
    """
    scores: dict[str, float] = {}
    meta: dict[str, QueryResult] = {}
    for i, ranked in enumerate(ranked_lists):
        weight = weights[i] if weights and i < len(weights) else 1.0
        for rank, item in enumerate(ranked, start=1):
            scores[item.id] = scores.get(item.id, 0.0) + weight / (k + rank)
            meta[item.id] = item
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if top_k is not None:
        ordered = ordered[:top_k]
    # 保留原对象全部字段（image_path/type/page 等），score 覆写为 RRF 分
    return [replace(meta[i], score=s) for i, s in ordered]
