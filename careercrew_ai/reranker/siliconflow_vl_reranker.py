"""硅基流动 VL 多模态精排（R4/R8）：Qwen3-VL-Reranker-8B。

候选含图片时，本地图片必须转 base64 data URI（不能传路径）。
低频调用（每查询仅 top_m 候选），走 API 省本地显存；失败回退原序。
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from careercrew_ai.reranker.base_reranker import BaseReranker
from careercrew_ai.vector_store.base_vector_store import QueryResult

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings


def _data_uri(path: str) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    try:
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    except Exception:
        return None
    return f"data:{mime};base64,{b64}"


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
        documents = []
        for c in candidates:
            content: list[dict] = [{"type": "text", "text": c.text or ""}]
            uri = _data_uri(c.image_path) if c.image_path else None
            if uri:
                content.append({"type": "image_url", "image_url": {"url": uri}})
            documents.append({"content": content})
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
