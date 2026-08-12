"""硅基流动 VL 多模态精排（R4/R8）：Qwen3-VL-Reranker-8B。

实测硅基流动 /rerank 接口的 documents 只接受纯字符串：传多模态对象
（text/image_url content 列表）会返回 HTTP 400，导致整次精排失败并
静默回退到 RRF 融合分（≈0.03，观感上"相关度全是 0.03"）。
故候选统一按文本精排；失败仍回退原序。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import requests

from careercrew_ai.reranker.base_reranker import BaseReranker
from careercrew_ai.vector_store.base_vector_store import QueryResult

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings


class SiliconFlowVLReranker(BaseReranker):
    def __init__(self, settings: Settings) -> None:
        cfg = settings.vlm
        self._model = cfg.rerank_model
        self._base_url = cfg.base_url.rstrip("/")
        self._api_key = cfg.api_key

    def rerank(
        self,
        query: str,
        candidates: list[QueryResult],
        top_k: int | None = None,
    ) -> list[QueryResult]:
        if not candidates:
            return []
        top_n = top_k if top_k is not None else len(candidates)
        documents = [c.text or "" for c in candidates]
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
                    "documents": documents,
                    "top_n": top_n,
                    "return_documents": False,
                },
                timeout=60,
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
                            id=c.id,
                            score=float(r.get("relevance_score", 0.0)),
                            text=c.text,
                            metadata=c.metadata,
                            image_path=c.image_path,
                            type=c.type,
                            page=c.page,
                        )
                    )
            return ranked or candidates[:top_n]
        except Exception:
            return candidates[:top_n] if top_k is not None else list(candidates)
