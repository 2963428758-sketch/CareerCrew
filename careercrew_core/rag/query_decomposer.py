"""Agentic RAG query decomposition（M4）。"""
from __future__ import annotations


class QueryDecomposer:
    """多跳查询分解为子查询。LLM 判断是否多跳，是则拆 1-3 个子查询。"""

    def decompose(self, query: str, llm) -> list[str]:
        prompt = (
            "判断以下求职相关查询是否为多跳/复杂问题。若是，拆成 1-3 个独立的子查询（每行一个，不要序号前缀）；"
            "若否，只返回原查询。\n查询: " + query
        )
        try:
            resp = llm.invoke(prompt)
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            lines: list[str] = []
            for l in content.splitlines():
                l = l.strip().lstrip("0123456789.、-• ")
                if l and l != query:
                    lines.append(l)
            return lines or [query]
        except Exception:
            return [query]
