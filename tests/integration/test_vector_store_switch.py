"""D5 配置切换 milvus/chroma 验证：工厂路由 + ChromaStore roundtrip。"""
from __future__ import annotations

from pathlib import Path

import pytest

from careercrew_ai.vector_store import VectorRecord, create_vector_store
from careercrew_ai.vector_store.chroma_store import ChromaStore
from careercrew_ai.vector_store.milvus_store import MilvusStore
from careercrew_core.state.settings import Settings


def test_factory_routes_milvus(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["vector_store"]["persist_path"] = str(tmp_path / "milvus")
    settings = Settings.model_validate(valid_config_data)  # backend=milvus_lite
    store = create_vector_store(settings)
    assert isinstance(store, MilvusStore)


def test_factory_routes_chroma(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["vector_store"]["persist_path"] = str(tmp_path / "chroma")
    valid_config_data["vector_store"]["backend"] = "chroma"
    settings = Settings.model_validate(valid_config_data)
    store = create_vector_store(settings)
    assert isinstance(store, ChromaStore)


@pytest.mark.integration
def test_chroma_store_roundtrip(tmp_path: Path, valid_config_data: dict) -> None:
    """ChromaStore dense roundtrip + filter + delete（dense-only 兜底）。"""
    valid_config_data["vector_store"]["persist_path"] = str(tmp_path / "chroma")
    settings = Settings.model_validate(valid_config_data)
    store = ChromaStore(settings, collection_name="test_chroma", dim=8)
    store.upsert([
        VectorRecord(id="a", dense=[1.0, 0, 0, 0, 0, 0, 0, 0], text="RAG 文档", metadata={"topic": "rag"}),
        VectorRecord(id="b", dense=[0, 1.0, 0, 0, 0, 0, 0, 0], text="Agent 文档", metadata={"topic": "agent"}),
    ])
    # dense 查询：[1,0,...] 最接近 a
    res = store.query([1.0, 0, 0, 0, 0, 0, 0, 0], top_k=2)
    assert len(res) >= 1
    assert res[0].id == "a"
    # filter
    res2 = store.query([1.0, 0, 0, 0, 0, 0, 0, 0], top_k=2, filters={"topic": "agent"})
    assert len(res2) == 1 and res2[0].id == "b"
    # delete
    n = store.delete_by_metadata({"topic": "rag"})
    assert n == 1
