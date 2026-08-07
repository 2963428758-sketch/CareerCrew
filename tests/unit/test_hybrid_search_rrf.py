"""D3 RRF 融合 + HybridSearch 测试。"""
from __future__ import annotations

from careercrew_ai.vector_store import QueryResult
from careercrew_core.rag.retrieval.fusion import rrf_fuse


def _qr(id_: str) -> QueryResult:
    return QueryResult(id=id_, score=0.0, text=f"text_{id_}", metadata={})


def test_rrf_fuse_single_list_preserves_order() -> None:
    fused = rrf_fuse([[_qr("a"), _qr("b"), _qr("c")]])
    assert [r.id for r in fused] == ["a", "b", "c"]
    assert fused[0].score > fused[1].score > fused[2].score


def test_rrf_fuse_two_lists_same_order() -> None:
    fused = rrf_fuse([[_qr("a"), _qr("b"), _qr("c")], [_qr("a"), _qr("b"), _qr("c")]], k=60)
    assert [r.id for r in fused] == ["a", "b", "c"]


def test_rrf_fuse_promotes_consensus() -> None:
    # a, b 在两路都靠前 -> top 2；c, d 只在一路 -> bottom 2
    fused = rrf_fuse([[_qr("a"), _qr("b"), _qr("c")], [_qr("b"), _qr("a"), _qr("d")]])
    assert set(r.id for r in fused[:2]) == {"a", "b"}
    assert set(r.id for r in fused[2:]) == {"c", "d"}


def test_rrf_fuse_top_k() -> None:
    fused = rrf_fuse([[_qr("a"), _qr("b"), _qr("c")]], top_k=2)
    assert len(fused) == 2
    assert fused[0].id == "a"


def test_hybrid_search_with_fake(valid_config_data: dict) -> None:
    from careercrew_ai.embedding import FakeEmbedding
    from careercrew_ai.vector_store import FakeVectorStore, VectorRecord
    from careercrew_core.rag.retrieval.hybrid_search import HybridSearch
    from careercrew_core.state.settings import Settings

    valid_config_data["embedding"]["provider"] = "fake"
    valid_config_data["vector_store"]["backend"] = "fake"
    settings = Settings.model_validate(valid_config_data)
    emb = FakeEmbedding(settings)
    store = FakeVectorStore(settings)
    store.upsert([
        VectorRecord(id="a", dense=[1.0, 0, 0, 0, 0, 0, 0, 0], text="RAG 文档", metadata={}),
        VectorRecord(id="b", dense=[0, 1.0, 0, 0, 0, 0, 0, 0], text="Agent 文档", metadata={}),
    ])
    hs = HybridSearch(emb, store, reranker=None, top_m=10)
    res = hs.search("RAG", top_k=2)
    assert len(res) <= 2
