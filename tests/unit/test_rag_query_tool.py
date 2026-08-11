"""rag_query 工具测试（mock MultimodalSearch）。"""
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


def test_rag_query_includes_image_line() -> None:
    hs = FakeHS([
        QueryResult(
            id="a", score=0.9, text="简历第一页",
            metadata={}, image_path="F:/x/page1.png", type="page", page=1,
        )
    ])
    t = make_rag_query_tool(hs)
    out = t.invoke({"query": "简历", "top_k": 3})
    assert "简历第一页" in out
    assert "[image: F:/x/page1.png]" in out


def test_rag_query_sink_receives_results() -> None:
    """sink 回调收到结构化 QueryResult（供来源标注）。"""
    hs = FakeHS([
        QueryResult(id="a", score=0.95, text="RAG 减少幻觉", metadata={"doc": "note"}),
        QueryResult(id="b", score=0.8, text="混合检索", metadata={"doc": "note"}, page=2),
    ])
    got: list[QueryResult] = []
    t = make_rag_query_tool(hs, sink=got.append)
    t.invoke({"query": "RAG", "top_k": 3})
    assert [r.id for r in got] == ["a", "b"]
    assert got[0].metadata["doc"] == "note"


def test_rag_query_sink_empty_results() -> None:
    """无检索结果时不触发 sink。"""
    got: list[QueryResult] = []
    t = make_rag_query_tool(FakeHS([]), sink=got.append)
    out = t.invoke({"query": "x", "top_k": 3})
    assert "无检索结果" in out
    assert got == []
