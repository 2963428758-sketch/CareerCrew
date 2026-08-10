"""多模态 ingestion pipeline 测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from careercrew_ai.embedding import FakeEmbedding
from careercrew_ai.vector_store import FakeVectorStore
from careercrew_core.rag.pipeline_multimodal import MultimodalIngestionPipeline
from careercrew_core.state.settings import Settings


def _fake_settings(valid_config_data: dict) -> Settings:
    valid_config_data["embedding"]["provider"] = "fake"
    valid_config_data["vector_store"]["backend"] = "fake"
    return Settings.model_validate(valid_config_data)


def test_ingest_text_with_fake(valid_config_data: dict) -> None:
    settings = _fake_settings(valid_config_data)
    emb = FakeEmbedding(settings)
    store = FakeVectorStore(settings)
    pipe = MultimodalIngestionPipeline(
        emb, store, contextual=False, chunk_size=30, chunk_overlap=5
    )
    n = pipe.ingest_text("这是第一段内容。这是第二段内容。这是第三段内容。", source="test.md")
    assert n >= 1
    # 验证可检索
    res = store.query(emb.encode(["第一段"]).dense[0], top_k=5)
    assert len(res) >= 1


def test_ingest_file_with_fake(tmp_path: Path, valid_config_data: dict) -> None:
    settings = _fake_settings(valid_config_data)
    f = tmp_path / "doc.md"
    f.write_text("# 标题\n\n一些内容。另一些内容。", encoding="utf-8")
    emb = FakeEmbedding(settings)
    store = FakeVectorStore(settings)
    pipe = MultimodalIngestionPipeline(
        emb, store, contextual=False, chunk_size=50, chunk_overlap=10
    )
    n = pipe.ingest_file(f)
    assert n >= 1


@pytest.mark.skipif(
    not Path("F:/AI_models/BAAI--bge-m3/snapshots/master").exists(),
    reason="BGE-M3 未下载到共享目录 F:/AI_models",
)
@pytest.mark.integration
def test_ingest_and_query_real(tmp_path: Path, valid_config_data: dict) -> None:
    """真实 BGE-M3 + Qdrant（内存模式）：ingest 文本 -> MultimodalSearch 检索。"""
    from careercrew_ai.embedding import create_embedding
    from careercrew_ai.vector_store import create_vector_store
    from careercrew_core.rag.retrieval.multimodal_search import MultimodalSearch

    valid_config_data["vector_store"]["backend"] = "qdrant"
    valid_config_data["vector_store"]["url"] = ":memory:"
    settings = Settings.model_validate(valid_config_data)
    emb = create_embedding(settings)
    store = create_vector_store(settings)
    pipe = MultimodalIngestionPipeline(
        emb, store, contextual=False, output_dir=tmp_path / "parsed",
        chunk_size=200, chunk_overlap=20,
    )
    n = pipe.ingest_text(
        "RAG 检索增强生成通过检索知识库减少幻觉。"
        "Agent 多智能体协同，supervisor 路由。"
        "LangGraph 状态机编排，支持 HITL。",
        source="note.md",
    )
    assert n >= 1
    ms = MultimodalSearch(emb, store, reranker=None, top_m=10)
    res = ms.search("RAG 怎么减少幻觉", top_k=2)
    assert len(res) >= 1
    assert "RAG" in res[0].text
