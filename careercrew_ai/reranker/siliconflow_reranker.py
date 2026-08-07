"""硅基流动 rerank API（D3）：bge-reranker-v2-m3 cross-encoder 重排。

低频（每查询仅 top_m 候选），走 API 省本地算力（ADR-6）。失败回退原序（对齐 5.7）。
已验证 API：POST /v1/rerank -> {results:[{index, relevance_score}]}。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import requests

from careercrew_ai.reranker.base_reranker import BaseReranker
from careercrew_ai.vector_store.base_vector_store import QueryResult

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings


class SiliconFlowReranker(BaseReranker):
    def __init__(self, settings: Settings) -> None:
        cfg = settings.rerank
        self._model = cfg.model
        self._base_url = cfg.base_url.rstrip("/")
        self._api_key = cfg.api_key
        self._top_m = cfg.top_m

    def rerank(self, query, candidates: list[QueryResult], top_k: int | None = None) -> list[QueryResult]:
        if not candidates:
            return []
        top_n = top_k if top_k is not None else len(candidates)
        try:
            resp = requests.post(
                f"{self._base_url}/rerank",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "query": query,
                    "documents": [c.text for c in candidates],
                    "top_n": top_n,
                    "return_documents": False,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            ranked: list[QueryResult] = []
            for r in data.get("results", []):
                idx = r["index"]
                if 0 <= idx < len(candidates):
                    c = candidates[idx]
                    ranked.append(
                        QueryResult(
                            id=c.id, score=float(r["relevance_score"]),
                            text=c.text, metadata=c.metadata,
                        )
                    )
            return ranked
        except Exception:
            # 失败回退原序（对齐 DEV_SPEC 5.7）
            return candidates[:top_k] if top_k is not None else list(candidates)
