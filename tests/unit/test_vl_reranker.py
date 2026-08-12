"""SiliconFlowVLReranker 单测：documents 必须是纯字符串。"""
from __future__ import annotations

from types import SimpleNamespace

from careercrew_ai.reranker.siliconflow_vl_reranker import SiliconFlowVLReranker
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
