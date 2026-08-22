"""MultimodalSearch 文本/图片查询路由与融合（fake 后端）。"""
from __future__ import annotations

from careercrew_ai.embedding import FakeEmbedding
from careercrew_ai.vector_store import FakeVectorStore, VectorRecord
from careercrew_core.rag.retrieval.multimodal_search import MultimodalSearch
from careercrew_core.state.settings import Settings


def _setup(valid_config_data: dict):
    valid_config_data["embedding"]["provider"] = "fake"
    valid_config_data["vector_store"]["backend"] = "fake"
    settings = Settings.model_validate(valid_config_data)
    emb = FakeEmbedding(settings)
    store = FakeVectorStore(settings)
    store.upsert([
        VectorRecord(id="a", dense=[1.0, 0, 0, 0, 0, 0, 0, 0], text="RAG 检索", metadata={}),
        VectorRecord(id="b", dense=[0, 1.0, 0, 0, 0, 0, 0, 0], text="Agent 智能体", metadata={}),
    ])
    return emb, store


def test_text_query_uses_routes_and_rrf(valid_config_data: dict) -> None:
    emb, store = _setup(valid_config_data)
    ms = MultimodalSearch(emb, store, reranker=None, top_m=10)
    res = ms.search("RAG", top_k=2)
    assert len(res) <= 2
    assert res[0].id == "a"


def test_image_query_without_reader_falls_back_to_text(valid_config_data: dict) -> None:
    emb, store = _setup(valid_config_data)
    ms = MultimodalSearch(emb, store, reranker=None, top_m=10)
    res = ms.search("RAG", top_k=2, image_path="F:/x/q.png")  # 无 visual encoder
    assert len(res) == 2


def test_image_query_with_reader_extracts_text(valid_config_data: dict) -> None:
    emb, store = _setup(valid_config_data)
    calls = []

    def reader(path: str) -> str:
        calls.append(path)
        return "RAG 检索增强"

    ms = MultimodalSearch(emb, store, reranker=None, top_m=10, image_reader=reader)
    res = ms.search("", top_k=2, image_path="F:/x/q.png")
    assert calls == ["F:/x/q.png"]
    assert res[0].id == "a"  # 提取出的文本命中 RAG 文档


def test_rerank_returns_reranked_order(valid_config_data: dict) -> None:
    emb, store = _setup(valid_config_data)

    class ReverseReranker:
        def rerank(self, query, candidates, top_k=None):
            return list(reversed(candidates))[:top_k] if top_k else list(reversed(candidates))

    ms = MultimodalSearch(emb, store, reranker=ReverseReranker(), top_m=10)
    res = ms.search("RAG", top_k=2)
    assert [r.id for r in res] == ["b", "a"]
