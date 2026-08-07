"""D4 rag_query 工具测试（mock HybridSearch）。"""
from __future__ import annotations

from careercrew_ai.vector_store import QueryResult
from careercrew_core.tools.internal.rag_query import make_rag_query_tool


class FakeHS:
    def __init__(self, results: list[QueryResult]) -> None:
        self.results = results

    def search(self, query: str, top_k: int = 5, filters: dict | None = None):
        return self.results


def test_rag_query_returns_formatted_results() -> None:
    hs = FakeHS([QueryResult(id="a", score=0.95, text="RAG 减少幻觉", metadata={})])
    t = make_rag_query_tool(hs)
    out = t.invoke({"query": "RAG", "top_k": 3})
    assert "RAG 减少幻觉" in out
    assert "0.950" in out
    assert "[1]" in out


def test_rag_query_empty() -> None:
    t = make_rag_query_tool(FakeHS([]))
    out = t.invoke({"query": "x", "top_k": 3})
    assert "无检索结果" in out
