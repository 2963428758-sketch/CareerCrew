"""Agentic RAG query router（M4）。

query -> kb(知识库) | web(网络) | memory(用户记忆)。关键词启发式 + 可选 LLM。
"""
from __future__ import annotations

_MEMORY_KEYWORDS = ["上次", "记得", "回忆", "之前", "历史", "面过", "投过", "面试过"]
_WEB_KEYWORDS = ["最新", "今天", "今年", "最近", "新闻", "行情", "趋势", "涨", "价格"]


class QueryRouter:
    def __init__(self, memory_keywords: list[str] | None = None, web_keywords: list[str] | None = None) -> None:
        self._memory_kw = memory_keywords or _MEMORY_KEYWORDS
        self._web_kw = web_keywords or _WEB_KEYWORDS

    def route(self, query: str) -> str:
        """关键词启发式路由：memory > web > kb。"""
        q = query.lower()
        if any(k in q for k in self._memory_kw):
            return "memory"
        if any(k in q for k in self._web_kw):
            return "web"
        return "kb"

    def route_llm(self, query: str, llm) -> str:
        """LLM 判断路由（更准）。"""
        prompt = (
            "这是求职相关查询，判断该路由到哪个来源：kb(知识库:八股/面经/JD/简历范本)、"
            "web(网络实时信息:最新薪资/公司动态/市场行情)、memory(用户历史记忆:面试/投递/offer)。"
            f"只输出一个词(kb/web/memory)。\n查询: {query}"
        )
        resp = llm.invoke(prompt)
        out = (resp.content if isinstance(resp.content, str) else str(resp.content)).strip().lower()
        for cand in ("kb", "web", "memory"):
            if cand in out:
                return cand
        return "kb"
