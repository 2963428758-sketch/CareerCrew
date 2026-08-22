"""D3 rerank 编排测试：None passthrough / FakeReranker / 失败回退。"""
from __future__ import annotations

from careercrew_ai.reranker import FakeReranker
from careercrew_ai.vector_store import QueryResult
from careercrew_core.rag.rerank import rerank


def test_rerank_none_passthrough() -> None:
    a = QueryResult(id="a", score=0.5, text="", metadata={})
    b = QueryResult(id="b", score=0.9, text="", metadata={})
    out = rerank(None, "q", [a, b], top_k=1)
    assert out == [a]  # 原序截断


def test_rerank_with_fake() -> None:
    rr = FakeReranker()
    a = QueryResult(id="b", score=0.9, text="", metadata={})
    b = QueryResult(id="a", score=0.5, text="", metadata={})
    out = rerank(rr, "q", [a, b])
    assert [r.id for r in out] == ["a", "b"]  # FakeReranker 按 id 字典序


def test_rerank_failure_fallback() -> None:
    class FailReranker:
        def rerank(self, query, candidates, top_k=None):
            raise RuntimeError("API 挂了")

    a = QueryResult(id="a", score=0.5, text="", metadata={})
    b = QueryResult(id="b", score=0.9, text="", metadata={})
    out = rerank(FailReranker(), "q", [a, b], top_k=1)
    assert out == [a]  # 失败回退原序截断


def test_rerank_empty_candidates() -> None:
    assert rerank(None, "q", []) == []
    assert rerank(FakeReranker(), "q", []) == []


def test_siliconflow_reranker_failure_logs_warning(monkeypatch, caplog) -> None:
    """SiliconFlowReranker 失败回退原序且 warning 留痕（对齐 5.7 + 可观测）。"""
    from types import SimpleNamespace

    from careercrew_ai.reranker.siliconflow_reranker import SiliconFlowReranker

    settings = SimpleNamespace(rerank=SimpleNamespace(
        model="BAAI/bge-reranker-v2-m3",
        base_url="https://api.siliconflow.cn/v1",
        api_key="test-key",
        top_m=5,
    ))

    def fake_post(url, headers=None, json=None, timeout=None):
        raise TimeoutError("rerank service hang")

    monkeypatch.setattr(
        "careercrew_ai.reranker.siliconflow_reranker.requests.post", fake_post
    )

    rr = SiliconFlowReranker(settings)
    a = QueryResult(id="a", score=0.5, text="t-a", metadata={})
    b = QueryResult(id="b", score=0.9, text="t-b", metadata={})
    with caplog.at_level("WARNING", logger="careercrew_ai.reranker.siliconflow_reranker"):
        out = rr.rerank("q", [a, b], top_k=2)

    assert out == [a, b]  # 原序回退
    assert any("rerank failed" in r.message for r in caplog.records)
    assert any(r.exc_info for r in caplog.records)
