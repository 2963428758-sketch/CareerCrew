"""CRAG 检索质量自评估（M5）：corrective RAG 的评估-纠错环。

对 rag_query 检索结果做 LLM 相关性判定（correct / ambiguous / incorrect）；
incorrect 时用 LLM 重写查询再检索一轮（max_rewrite 次），合并去重后返回。
评估记录随结果返回，供上层展示与 LangSmith 追踪（Grounding 证据链）。

接线：make_rag_query_tool(assessor=...) 注入；默认 None 行为不变
（开关 rag.retrieval.crag）。
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_PROMPT = (
    "你是检索质量评估器。判断以下文档片段能否回答用户问题。\n"
    "问题：{query}\n\n"
    "文档片段：\n{docs}\n\n"
    "输出 JSON：{{\"verdict\": \"correct|ambiguous|incorrect\", "
    "\"rewritten_query\": \"仅当 incorrect 时给出更利于检索的改写\"}}\n"
    "标准：correct=至少一段能直接支撑回答；ambiguous=部分相关但不确定；"
    "incorrect=全部偏题。只输出 JSON。"
)


def _parse_verdict(content: str) -> dict:
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return {"verdict": "ambiguous", "rewritten_query": ""}
    try:
        data = json.loads(m.group(0))
        verdict = str(data.get("verdict", "ambiguous")).lower()
        if verdict not in ("correct", "ambiguous", "incorrect"):
            verdict = "ambiguous"
        return {"verdict": verdict,
                "rewritten_query": str(data.get("rewritten_query") or "")}
    except Exception:
        return {"verdict": "ambiguous", "rewritten_query": ""}


def assess(query: str, docs: list[Any], llm: Any) -> dict:
    """LLM 判定检索结果质量；解析失败保守返回 ambiguous。"""
    if not docs:
        return {"verdict": "incorrect", "rewritten_query": ""}
    joined = "\n".join(
        f"[{i}] {getattr(d, 'text', '') or ''}"[:400] for i, d in enumerate(docs)
    )
    try:
        resp = llm.invoke(_PROMPT.format(query=query[:500], docs=joined))
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return _parse_verdict(content)
    except Exception:
        logger.warning("CRAG assess 失败，保守放行", exc_info=True)
        return {"verdict": "ambiguous", "rewritten_query": ""}


class RetrievalAssessor:
    """评估 + 纠错重检。search_fn(query)->docs 由调用方注入（可带原 filters）。"""

    def __init__(self, llm: Any, search_fn: Callable[[str], list[Any]],
                 max_rewrite: int = 1):
        self._llm = llm
        self._search_fn = search_fn
        self._max_rewrite = max_rewrite

    def run(self, query: str, top_k: int) -> tuple[list[Any], dict]:
        """返回 (最终 docs, 评估记录)。incorrect 才触发重写重检；合并按 id 去重。"""
        docs = self._search_fn(query)
        trail: list[dict] = []
        seen_ids = {getattr(d, "id", None) for d in docs}

        for _ in range(self._max_rewrite + 1):
            verdict = assess(query, docs, self._llm)
            trail.append({"query": query, "verdict": verdict["verdict"]})
            if verdict["verdict"] != "incorrect":
                break
            rewritten = (verdict.get("rewritten_query") or "").strip()
            if not rewritten or rewritten == query:
                break
            query = rewritten
            extra = [d for d in self._search_fn(query)
                     if getattr(d, "id", None) not in seen_ids]
            for d in extra:
                seen_ids.add(getattr(d, "id", None))
                docs.append(d)

        meta = {"crag": True, "final_query": query,
                "trail": [t["verdict"] for t in trail]}
        return docs[:top_k] if top_k else docs, meta
