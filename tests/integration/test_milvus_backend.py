"""D2 Milvus 后端集成测试：真实 milvus-lite，dense+sparse hybrid roundtrip。"""
from __future__ import annotations

from pathlib import Path

import pytest

from careercrew_ai.vector_store import VectorRecord
from careercrew_ai.vector_store.milvus_store import MilvusStore
from careercrew_core.state.settings import Settings


@pytest.mark.integration
def test_milvus_store_roundtrip(tmp_path: Path, valid_config_data: dict) -> None:
    valid_config_data["vector_store"]["persist_path"] = str(tmp_path / "milvus")
    settings = Settings.model_validate(valid_config_data)
    store = MilvusStore(settings, collection_name="test_kb", dim=8)

    store.upsert([
        VectorRecord(id="a", dense=[1.0, 0, 0, 0, 0, 0, 0, 0], text="RAG 检索增强生成",
                     metadata={"source": "note.md", "topic": "rag"}, sparse={0: 0.5, 1: 0.3}),
        VectorRecord(id="b", dense=[0, 1.0, 0, 0, 0, 0, 0, 0], text="Agent 多智能体",
                     metadata={"source": "note.md", "topic": "agent"}, sparse={2: 0.6}),
        VectorRecord(id="c", dense=[1.0, 1.0, 0, 0, 0, 0, 0, 0], text="RAG + Agent 结合",
                     metadata={"source": "blog.md", "topic": "rag"}, sparse={0: 0.4, 2: 0.2}),
    ])

    # dense 查询
    res = store.query([1.0, 0, 0, 0, 0, 0, 0, 0], top_k=3)
    assert len(res) >= 1
    assert res[0].id in ("a", "c")  # dim0=1 最相似

    # hybrid 查询（dense + sparse）
    res2 = store.query([1.0, 0, 0, 0, 0, 0, 0, 0], top_k=3, sparse={0: 0.5})
    assert len(res2) >= 1
    assert res2[0].id == "a"  # dense + sparse 双路命中 a

    # filter（dynamic field 过滤）
    res3 = store.query([1.0, 0, 0, 0, 0, 0, 0, 0], top_k=3, filters={"topic": "agent"})
    assert len(res3) == 1 and res3[0].id == "b"

    # get_by_ids（含不存在的 id）
    got = store.get_by_ids(["a", "zzz"])
    assert [r.id for r in got] == ["a"]

    # delete_by_metadata
    n = store.delete_by_metadata({"source": "note.md"})
    assert n == 2
    assert [r.id for r in store.get_by_ids(["a", "b", "c"])] == ["c"]
