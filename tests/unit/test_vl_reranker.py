"""SiliconFlowVLReranker 单测：documents 必须是纯字符串 + 失败留痕回退。"""
from __future__ import annotations

from types import SimpleNamespace

from careercrew_ai.reranker.siliconflow_vl_reranker import (
    _RERANK_TIMEOUT_S,
    SiliconFlowVLReranker,
)
from careercrew_ai.vector_store import QueryResult


def _settings():
    return SimpleNamespace(vlm=SimpleNamespace(
        rerank_model="Qwen/Qwen3-VL-Reranker-8B",
        base_url="https://api.siliconflow.cn/v1",
        api_key="test-key",
    ))


def test_vl_reranker_sends_plain_strings(monkeypatch) -> None:
    """API 只接受纯字符串 documents（传多模态对象会 400 导致回退 RRF 分）。"""
    captured: dict = {}

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.3},
                ]
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr(
        "careercrew_ai.reranker.siliconflow_vl_reranker.requests.post", fake_post
    )

    rr = SiliconFlowVLReranker(_settings())
    cands = [
        QueryResult(id="a", score=0.0, text="今天天气不错", metadata={}),
        QueryResult(id="b", score=0.0, text="RAG 检索增强生成", metadata={}),
    ]
    out = rr.rerank("什么是 RAG", cands, top_k=2)

    assert captured["url"] == "https://api.siliconflow.cn/v1/rerank"
    docs = captured["json"]["documents"]
    assert all(isinstance(d, str) for d in docs)
    assert docs == ["今天天气不错", "RAG 检索增强生成"]

    # 按 relevance_score 重排，分数透传
    assert [c.id for c in out] == ["b", "a"]
    assert out[0].score == 0.9
    assert out[1].score == 0.3


def test_vl_reranker_timeout_is_bounded(monkeypatch) -> None:
    """请求超时必须有界（15s），不能让上游挂起拖死检索链路。"""
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["timeout"] = timeout
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "careercrew_ai.reranker.siliconflow_vl_reranker.requests.post", fake_post
    )

    rr = SiliconFlowVLReranker(_settings())
    cands = [QueryResult(id="a", score=0.5, text="t", metadata={})]
    assert rr.rerank("q", cands) == cands  # 回退原序
    assert captured["timeout"] == _RERANK_TIMEOUT_S


def test_vl_reranker_failure_logs_warning_and_falls_back(monkeypatch, caplog) -> None:
    """失败必须 warning 留痕（否则服务挂了只表现为检索质量莫名下降）并回退原序。"""

    def fake_post(url, headers=None, json=None, timeout=None):
        raise TimeoutError("rerank service hang")

    monkeypatch.setattr(
        "careercrew_ai.reranker.siliconflow_vl_reranker.requests.post", fake_post
    )

    rr = SiliconFlowVLReranker(_settings())
    a = QueryResult(id="a", score=0.5, text="t-a", metadata={})
    b = QueryResult(id="b", score=0.9, text="t-b", metadata={})
    with caplog.at_level("WARNING", logger="careercrew_ai.reranker.siliconflow_vl_reranker"):
        out = rr.rerank("q", [a, b], top_k=2)

    assert out == [a, b]  # 原序回退
    assert any("vl_rerank failed" in r.message for r in caplog.records)
    assert any(r.exc_info for r in caplog.records)  # 带异常详情


def test_vl_reranker_top_k_truncates_on_fallback(monkeypatch) -> None:
    """top_k 截断语义在失败回退路径上保持一致。"""

    def fake_post(url, headers=None, json=None, timeout=None):
        raise RuntimeError("500")

    monkeypatch.setattr(
        "careercrew_ai.reranker.siliconflow_vl_reranker.requests.post", fake_post
    )

    rr = SiliconFlowVLReranker(_settings())
    cands = [
        QueryResult(id=f"c{i}", score=0.1 * i, text="t", metadata={}) for i in range(5)
    ]
    out = rr.rerank("q", cands, top_k=3)
    assert [c.id for c in out] == ["c0", "c1", "c2"]
