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


def _record(doc: str, owner: str, visibility: str, text: str = "t"):
    return VectorRecord(
        id=f"{doc}-p0", dense=[0.1] * 1024,
        text=text,
        metadata={"doc": doc, "source": f"{doc}.pdf", "category": "knowledge",
                  "owner_user_id": owner, "visibility": visibility},
    )


def test_access_filter_sees_public_and_own_private_only(valid_config_data):
    store = _store(valid_config_data)
    store.upsert([
        _record("mine", "u_001", "private"),
        _record("public-doc", "u_002", "public"),
        _record("theirs", "u_002", "private"),
    ])
    hits = store.query([0.1] * 1024, top_k=10, filters={"__access_user": "u_001"})
    docs = {h.id for h in hits}
    assert docs == {"mine-p0", "public-doc-p0"}


def test_access_filter_key_does_not_leak_into_must(valid_config_data):
    store = _store(valid_config_data)
    store.upsert([_record("cat-doc", "u_001", "private")])
    hits = store.query(
        [0.1] * 1024, top_k=10,
        filters={"__access_user": "u_001", "category": "knowledge"},
    )
    assert {h.id for h in hits} == {"cat-doc-p0"}


def test_list_docs_separates_same_name_by_visibility(valid_config_data):
    store = _store(valid_config_data)
    store.upsert([
        _record("same", "u_001", "private"),
        _record("same", "u_002", "public"),
    ])
    docs = store.list_docs(filters={"__access_user": "u_001"})
    by_vis = {d["visibility"] for d in docs}
    assert by_vis == {"private", "public"}
    public = next(d for d in docs if d["visibility"] == "public")
    assert public["owner_user_id"] == "u_002"


def test_set_payload_by_filter_toggles_visibility(valid_config_data):
    store = _store(valid_config_data)
    store.upsert([_record("publish-me", "u_001", "private")])
    n = store.set_payload_by_filter(
        {"visibility": "public"},
        {"owner_user_id": "u_001", "doc": "publish-me"},
    )
    assert n == 1
    assert store.count(filters={"doc": "publish-me", "visibility": "public"}) == 1
    assert store.count(filters={"doc": "publish-me", "visibility": "private"}) == 0
    # None 值删除键
    store.set_payload_by_filter({"visibility": None}, {"doc": "publish-me"})
    assert store.count(filters={"doc": "publish-me"}) == 1


def test_upsert_reads_owner_from_owner_user_id_first(valid_config_data):
    store = _store(valid_config_data)
    store.upsert([VectorRecord(
        id="legacy-id", dense=[0.1] * 1024,
        metadata={"doc": "d", "user_id": "u_001"},
    )])
    store.upsert([VectorRecord(
        id="legacy-id", dense=[0.1] * 1024,
        metadata={"doc": "d", "owner_user_id": "u_001"},
    )])
    # 两种键名必须映射到同一物理 ID：合计只有 1 个点
    assert store.count(filters={"doc": "d"}) == 1
