"""VLM 看图回答（多模态 RAG 生成层）。

检索出的 top_k 页面/对象图（base64 data URI）+ 文本块 -> settings.vlm.model（zai-org/GLM-4.5V）生成。
API 失败回退文本生成（主 LLM + 文本块），sources 始终返回。
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING

from careercrew_ai.vector_store.base_vector_store import QueryResult

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings

_MAX_IMAGES = 4
_MAX_SOURCE_CHARS = 6000


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


def _sources_payload(results: list[QueryResult]) -> list[dict]:
    out = []
    for r in results:
        out.append(
            {
                "id": r.id,
                "score": round(float(r.score), 4),
                "text": r.text,
                "image_path": r.image_path,
                "type": r.type,
                "page": r.page,
                "doc": r.metadata.get("doc", ""),
            }
        )
    return out


def vlm_answer(
    settings: "Settings",
    question: str,
    results: list[QueryResult],
    llm=None,
) -> dict:
    """检索结果 -> VLM 看图回答。返回 {answer, sources}。"""
    sources = _sources_payload(results)
    text_blocks = "\n\n".join(f"[{i + 1}] {r.text}" for i, r in enumerate(results))
    text_blocks = text_blocks[:_MAX_SOURCE_CHARS]

    content: list[dict] = [{"type": "text", "text": f"问题：{question}\n\n检索到的文档片段：\n{text_blocks}\n\n请结合图片与文档片段回答。"}]
    seen: set[str] = set()
    for r in results:
        if r.image_path and r.image_path not in seen and len(seen) < _MAX_IMAGES:
            uri = _data_uri(r.image_path)
            if uri:
                content.append({"type": "image_url", "image_url": {"url": uri}})
                seen.add(r.image_path)

    try:
        from openai import OpenAI

        client = OpenAI(base_url=settings.vlm.base_url, api_key=settings.vlm.api_key)
        resp = client.chat.completions.create(
            model=settings.vlm.model,
            messages=[{"role": "user", "content": content}],
            temperature=0.3,
            max_tokens=2048,
            timeout=120,
        )
        answer = (resp.choices[0].message.content or "").strip()
        return {"answer": answer, "sources": sources}
    except Exception:
        pass

    # 回退：文本生成（主 LLM + 文本块）
    fallback_prompt = (
        f"问题：{question}\n\n检索到的文档片段（多模态回答不可用，仅文本）：\n{text_blocks}\n\n请基于片段回答。"
    )
    try:
        if llm is not None:
            resp = llm.invoke(fallback_prompt)
            answer = resp.content if isinstance(resp.content, str) else str(resp.content)
        else:
            answer = "（VLM 回答不可用，且未提供文本生成回退）"
    except Exception:
        answer = "（VLM 回答不可用）"
    return {"answer": answer.strip(), "sources": sources}
