"""VL 多模态精排测试（mock requests.post）。"""
from __future__ import annotations

from careercrew_ai.reranker.siliconflow_vl_reranker import SiliconFlowVLReranker
from careercrew_ai.vector_store import QueryResult
from careercrew_core.state.settings import Settings


def _cands():
    return [
        QueryResult(id="a", score=0.5, text="文档 A", metadata={}),
        QueryResult(id="b", score=0.6, text="文档 B", metadata={}),
    ]


def test_vl_rerank_reorders(valid_config_data: dict, monkeypatch) -> None:
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [
                {"index": 1, "relevance_score": 0.9, "image_tokens": 10},
                {"index": 0, "relevance_score": 0.8, "image_tokens": 5},
            ]}

    monkeypatch.setattr(
        "careercrew_ai.reranker.siliconflow_vl_reranker.requests.post",
        lambda *a, **k: FakeResp(),
    )
    rr = SiliconFlowVLReranker(Settings.model_validate(valid_config_data))
    out = rr.rerank("q", _cands(), top_k=2)
    assert [c.id for c in out] == ["b", "a"]
    assert out[0].score == 0.9


def test_vl_rerank_fallback_on_api_error(valid_config_data: dict, monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(
        "careercrew_ai.reranker.siliconflow_vl_reranker.requests.post", boom
    )
    rr = SiliconFlowVLReranker(Settings.model_validate(valid_config_data))
    out = rr.rerank("q", _cands(), top_k=1)
    assert [c.id for c in out] == ["a"]  # 回退原序截断
