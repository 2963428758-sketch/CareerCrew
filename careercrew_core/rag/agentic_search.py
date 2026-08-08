"""Agentic RAG 编排（M4）：路由 -> (分解 -> 子查询检索) -> rrf_fuse 融合。"""
from __future__ import annotations

from careercrew_ai.vector_store.base_vector_store import QueryResult
from careercrew_core.rag.agent_router import QueryRouter
from careercrew_core.rag.query_decomposer import QueryDecomposer
from careercrew_core.rag.retrieval.fusion import rrf_fuse


class AgenticSearch:
    """Agentic RAG：按路由检索（kb/web/memory），多跳则分解子查询并用 rrf_fuse 融合。"""

    def __init__(
        self,
        hybrid_search,
        router: QueryRouter | None = None,
        decomposer: QueryDecomposer | None = None,
        llm=None,
        web_search=None,      # callable(query, top_k) -> list[QueryResult]
        memory_search=None,   # callable(query, top_k) -> list[QueryResult]
        rr_fuse_k: int = 60,
    ) -> None:
        self._hybrid = hybrid_search
        self._router = router or QueryRouter()
        self._decomposer = decomposer
        self._llm = llm
        self._web = web_search
        self._memory = memory_search
        self._k = rr_fuse_k

    def search(self, query: str, top_k: int = 5) -> list[QueryResult]:
        route = self._router.route(query)
        main = self._retrieve(query, route, top_k)

        # 多跳：分解子查询检索 + rrf_fuse 融合
        if self._decomposer is not None and self._llm is not None:
            subs = self._decomposer.decompose(query, self._llm)
            if len(subs) > 1:
                sub_results = [r for r in (self._retrieve(sq, route, top_k) for sq in subs) if r]
                if len(sub_results) > 1:
                    return rrf_fuse([main] + sub_results, k=self._k, top_k=top_k)
        return main

    def _retrieve(self, query: str, route: str, top_k: int) -> list[QueryResult]:
        if route == "memory" and self._memory is not None:
            return self._memory(query, top_k)
        if route == "web" and self._web is not None:
            return self._web(query, top_k)
        return self._hybrid.search(query, top_k=top_k)
