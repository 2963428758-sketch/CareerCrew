"""QdrantStore 文本双向量 roundtrip（内存模式，无外部依赖）。"""
from __future__ import annotations

from careercrew_ai.vector_store.base_vector_store import VectorRecord
from careercrew_ai.vector_store.qdrant_store import QdrantStore
from careercrew_core.state.settings import Settings


def _store(valid_config_data: dict, collection: str | None = None) -> QdrantStore:
    settings = Settings.model_validate(valid_config_data)
    return QdrantStore(settings, collection_name=collection)


def test_roundtrip(valid_config_data: dict) -> None:
    store = _store(valid_config_data)
    store.upsert([
        VectorRecord(
            id="doc1_p001", dense=[0.1] * 1024, sparse={1: 0.5, 2: 0.3},
            text="页面一：RAG 混合检索",
            metadata={"doc": "doc1", "page": 1, "type": "page",
                      "source": "t.md", "image_path": "F:/x/p1.png"},
        ),
        VectorRecord(
            id="doc1_p002", dense=[0.9] * 1024, sparse={3: 0.7},
            text="页面二：多模态视觉编码",
            metadata={"doc": "doc1", "page": 2, "type": "page",
                      "source": "t.md", "image_path": "F:/x/p2.png"},
        ),
    ])
    assert store.count() == 2

    routes = store.query_routes(dense=[0.9] * 1024, sparse={3: 0.7}, top_m=2)
    assert set(routes) == {"text_dense", "text_sparse"}
    assert routes["text_dense"][0].id == "doc1_p002"

    top = store.query([0.9] * 1024, top_k=2, sparse={3: 0.7})
    assert top[0].id == "doc1_p002"
    assert top[0].image_path == "F:/x/p2.png"
    assert top[0].type == "page" and top[0].page == 2

    got = store.get_by_ids(["doc1_p001"])
    assert got[0].id == "doc1_p001"
    assert len(got[0].dense) == 1024
    assert got[0].sparse == {1: 0.5, 2: 0.3}

    assert store.delete_by_metadata({"doc": "doc1"}) == 2
    assert store.count() == 0


def test_episodic_collection_same_schema(valid_config_data: dict) -> None:
    store = _store(valid_config_data, collection="careercrew_episodic")
    store.upsert([
        VectorRecord(id="m1", dense=[1.0] * 1024, sparse={1: 0.9},
                     text="记忆", metadata={"type": "interview"}),
    ])
    routes = store.query_routes(dense=[1.0] * 1024, sparse={1: 0.9}, top_m=2)
    assert set(routes) == {"text_dense", "text_sparse"}
    assert store.count() == 1


def test_filter_delete_by_metadata(valid_config_data: dict) -> None:
    store = _store(valid_config_data)
    store.upsert([
        VectorRecord(id="a_p001", dense=[0.1] * 1024, text="a",
                     metadata={"doc": "a", "type": "page", "page": 1}),
        VectorRecord(id="b_p001", dense=[0.1] * 1024, text="b",
                     metadata={"doc": "b", "type": "page", "page": 1}),
    ])
    assert store.delete_by_metadata({"doc": "a"}) == 1
    assert [r.id for r in store.get_by_ids(["a_p001", "b_p001"])] == ["b_p001"]
