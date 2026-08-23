"""ColBERT late-interaction 精排（M7）。

BGE-M3 一次前向产出 colbert token 级矩阵；本模块把它变成检索链里的本地精排级：
- 入库侧（可选）：chunk 的 colbert 向量随 payload 落库（colbert_store 开关，默认关——
  每 chunk 数百 KB，存量库需重建才生效）；
- 查询侧：query colbert 矩阵与候选 doc 矩阵做 MaxSim（每个 query token 对文档所有
  token 取最大相似度再求和），得分归一后重排候选。

为什么不走 Qdrant multivector（MAX_SIM named vector）：需要改 collection schema
并重建索引；payload 方案零迁移、开关即用。后续切 multivector 见 DEV_SPEC M7 备注。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def max_sim_score(q_vecs: list[list[float]], d_vecs: list[list[float]]) -> float:
    """late-interaction MaxSim：sum_i max_j <q_i, d_j>（点积近似，未除温度）。"""
    if not q_vecs or not d_vecs:
        return 0.0
    total = 0.0
    for q in q_vecs:
        best = max(
            (sum(a * b for a, b in zip(q, d, strict=False)) for d in d_vecs),
            default=0.0,
        )
        total += best
    return total


def _to_lists(vecs: Any) -> list[list[float]]:
    """np.ndarray (tokens, dim) / 嵌套 list 统一转嵌套 list。"""
    if vecs is None:
        return []
    try:  # numpy 优先（BGE-M3 返回 ndarray）
        import numpy as np

        if isinstance(vecs, np.ndarray):
            return [[float(x) for x in row] for row in vecs]
    except ImportError:
        pass
    return [[float(x) for x in row] for row in vecs]


class ColBERTLocalReranker:
    """从候选 payload 取 doc colbert 矩阵与 query 矩阵做 MaxSim 重排。

    无 colbert 数据的候选保持原相对顺序排在有分候选之后（稳定降级）。
    """

    name = "colbert_local"

    def __init__(self, embedding, top_k: int | None = None):
        self._embedding = embedding
        self._top_k = top_k

    def _doc_vecs(self, result) -> list[list[float]]:
        metadata = getattr(result, "metadata", None) or {}
        return _to_lists(metadata.get("colbert"))

    def rerank(self, query: str, results: list, top_k: int = 10) -> list:
        try:
            emb = self._embedding.encode([query])
            q_vecs = _to_lists(emb.colbert[0] if emb.colbert else None)
        except Exception:
            logger.warning("colbert query encode 失败，回退原序", exc_info=True)
            return results[:top_k]
        if not q_vecs:
            return results[:top_k]

        scored: list[tuple[float, int, Any]] = []
        for i, r in enumerate(results):
            dv = self._doc_vecs(r)
            # 有 colbert 数据的参与打分；无数据的给 -inf 保持尾部原序
            scored.append((max_sim_score(q_vecs, dv) if dv else float("-inf"), i, r))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [r for _, _, r in scored][:top_k]
