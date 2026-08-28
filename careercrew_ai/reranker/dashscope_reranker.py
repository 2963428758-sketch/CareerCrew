"""阿里云百炼 DashScope rerank API：gte-rerank-v2 / qwen3-rerank 重排。

API 规范：
POST https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank
Header: Authorization: Bearer {DASHSCOPE_API_KEY}
Body: {
    "model": "gte-rerank-v2",
    "input": {
        "query": "...",
        "documents": ["..."]
    },
    "parameters": {
        "top_n": 10,
        "return_documents": false
    }
}
Response: {
    "output": {
        "results": [
            {"index": 0, "relevance_score": 0.95},
            ...
        ]
    }
}
失败自动优雅降级回退原序（对齐 DEV_SPEC 5.7）。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import requests

from careercrew_ai.reranker.base_reranker import BaseReranker
from careercrew_ai.vector_store.base_vector_store import QueryResult

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings

logger = logging.getLogger(__name__)

_RERANK_TIMEOUT_S = 15


class DashScopeReranker(BaseReranker):
    def __init__(self, settings: Settings) -> None:
        cfg = settings.rerank
        self._model = cfg.model or "gte-rerank-v2"
        base_url = (cfg.base_url or "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank").rstrip("/")
        if not base_url.endswith("/text-rerank/text-rerank"):
            if base_url.endswith("/text-rerank"):
                base_url = f"{base_url}/text-rerank"
            else:
                base_url = f"{base_url}/text-rerank/text-rerank"
        self._url = base_url
        self._api_key = cfg.api_key
        self._top_m = cfg.top_m

    def rerank(self, query: str, candidates: list[QueryResult], top_k: int | None = None) -> list[QueryResult]:
        if not candidates:
            return []
        top_n = top_k if top_k is not None else len(candidates)
        try:
            resp = requests.post(
                self._url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "input": {
                        "query": query,
                        "documents": [c.text for c in candidates],
                    },
                    "parameters": {
                        "top_n": top_n,
                        "return_documents": False,
                    },
                },
                timeout=_RERANK_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("output", {}).get("results", []) or data.get("results", [])
            ranked: list[QueryResult] = []
            for r in results:
                idx = r.get("index")
                score = r.get("relevance_score")
                if idx is not None and 0 <= idx < len(candidates):
                    c = candidates[idx]
                    ranked.append(
                        QueryResult(
                            id=c.id,
                            score=float(score) if score is not None else 0.0,
                            text=c.text,
                            metadata=c.metadata,
                        )
                    )
            return ranked if ranked else candidates[:top_k]
        except Exception:
            logger.warning(
                "DashScope rerank 失败（model=%s, candidates=%d），已优雅降级回退原始检索顺序",
                self._model,
                len(candidates),
                exc_info=True,
            )
            return candidates[:top_k] if top_k is not None else list(candidates)
