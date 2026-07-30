"""A4 AI 基础层工厂与契约测试。

测试即文档：
- create_llm 用 init_chat_model 构造 ChatOpenAI，base_url 注入到 openai_api_base（langchain-openai 1.x）。
- 三个抽象工厂按 provider/backend 路由；未实现的真后端抛 NotImplementedError（D1-D3 填充）。
- FakeVectorStore upsert->query->filter->delete roundtrip 契约约束 shape。
"""
from __future__ import annotations

import pytest

from careercrew_ai.embedding import EmbeddingOutput, FakeEmbedding, create_embedding
from careercrew_ai.llm import create_llm
from careercrew_ai.reranker import FakeReranker, NoneReranker, create_reranker
from careercrew_ai.vector_store import (
    FakeVectorStore,
    QueryResult,
    VectorRecord,
    create_vector_store,
)
from careercrew_core.state.settings import Settings


# ── create_llm ──


def test_create_llm_injects_base_url(valid_config_data: dict) -> None:
    settings = Settings.model_validate(valid_config_data)
    llm = create_llm(settings)
    # langchain-openai 1.x 把 base_url 存为 openai_api_base
    assert getattr(llm, "openai_api_base", None) == settings.llm.base_url
    assert llm.model_name == settings.llm.model


def test_create_llm_override_temperature(valid_config_data: dict) -> None:
    settings = Settings.model_validate(valid_config_data)
    llm = create_llm(settings, temperature=0.0)
    assert llm.temperature == 0.0


# ── embedding factory + 契约 ──


def test_create_embedding_routes_to_fake(valid_config_data: dict) -> None:
    valid_config_data["embedding"]["provider"] = "fake"
    settings = Settings.model_validate(valid_config_data)
    emb = create_embedding(settings)
    assert isinstance(emb, FakeEmbedding)
    out = emb.encode(["hello", "world!"])
    assert isinstance(out, EmbeddingOutput)
    assert out.dense.shape == (2, 8)  # n_texts=2, dim=8


def test_create_embedding_bge_m3_not_yet_implemented(valid_config_data: dict) -> None:
    settings = Settings.model_validate(valid_config_data)  # provider=bge_m3_local
    with pytest.raises(NotImplementedError):
        create_embedding(settings)


# ── vector store factory + 契约 ──


def test_create_vector_store_routes_to_fake(valid_config_data: dict) -> None:
    valid_config_data["vector_store"]["backend"] = "fake"
    settings = Settings.model_validate(valid_config_data)
    vs = create_vector_store(settings)
    assert isinstance(vs, FakeVectorStore)
    # roundtrip: upsert -> query -> filter -> get -> delete
    vs.upsert([
        VectorRecord(id="a", dense=[1.0, 0.0], text="foo", metadata={"k": "v1"}),
        VectorRecord(id="b", dense=[0.0, 1.0], text="bar", metadata={"k": "v2"}),
    ])
    res = vs.query([1.0, 0.0], top_k=2)
    assert len(res) == 2
    assert res[0].id == "a"  # cosine 最相似
    assert res[0].score > res[1].score
    # filter
    res_f = vs.query([1.0, 0.0], top_k=2, filters={"k": "v2"})
    assert len(res_f) == 1 and res_f[0].id == "b"
    # get_by_ids（含不存在的 id）
    got = vs.get_by_ids(["a", "zzz"])
    assert [r.id for r in got] == ["a"]
    # delete_by_metadata
    n = vs.delete_by_metadata({"k": "v1"})
    assert n == 1
    assert vs.get_by_ids(["a"]) == []


def test_create_vector_store_milvus_not_yet_implemented(valid_config_data: dict) -> None:
    settings = Settings.model_validate(valid_config_data)  # backend=milvus_lite
    with pytest.raises(NotImplementedError):
        create_vector_store(settings)


# ── reranker factory + 契约 ──


def test_create_reranker_none_passthrough(valid_config_data: dict) -> None:
    valid_config_data["rerank"]["backend"] = "none"
    valid_config_data["rerank"]["api_key"] = ""
    settings = Settings.model_validate(valid_config_data)
    rr = create_reranker(settings)
    assert isinstance(rr, NoneReranker)
    cands = [
        QueryResult(id="a", score=0.5, text="x", metadata={}),
        QueryResult(id="b", score=0.9, text="y", metadata={}),
    ]
    out = rr.rerank("q", cands, top_k=1)
    assert out == cands[:1]  # 原序截断


def test_create_reranker_fake(valid_config_data: dict) -> None:
    valid_config_data["rerank"]["backend"] = "fake"
    valid_config_data["rerank"]["api_key"] = ""
    settings = Settings.model_validate(valid_config_data)
    rr = create_reranker(settings)
    assert isinstance(rr, FakeReranker)
    cands = [
        QueryResult(id="b", score=0.9, text="y", metadata={}),
        QueryResult(id="a", score=0.5, text="x", metadata={}),
    ]
    out = rr.rerank("q", cands)
    assert [c.id for c in out] == ["a", "b"]  # 按 id 字典序


def test_create_reranker_siliconflow_not_yet_implemented(valid_config_data: dict) -> None:
    settings = Settings.model_validate(valid_config_data)  # backend=siliconflow
    with pytest.raises(NotImplementedError):
        create_reranker(settings)
