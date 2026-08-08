"""I 情景记忆向量索引 + memory_search 测试。"""
from __future__ import annotations

from careercrew_ai.embedding import FakeEmbedding
from careercrew_ai.vector_store import FakeVectorStore
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry
from careercrew_core.memory.vector_index import VectorIndex
from careercrew_core.state.settings import Settings
from careercrew_core.tools.internal.memory_search import make_memory_search_tool


def _settings(valid_config_data: dict) -> Settings:
    valid_config_data["embedding"]["provider"] = "fake"
    valid_config_data["vector_store"]["backend"] = "fake"
    return Settings.model_validate(valid_config_data)


def test_vector_index_roundtrip(tmp_path, valid_config_data: dict) -> None:
    settings = _settings(valid_config_data)
    em = EpisodicMemory(tmp_path / "t.jsonl")
    em.write(MemoryEntry(type="interview_qa", content={"q": "RAG 怎么减幻觉", "score": 8}))
    em.write(MemoryEntry(type="job_match", content={"company": "字节", "score": 0.9}))
    vi = VectorIndex(FakeEmbedding(settings), FakeVectorStore(settings), em)
    assert vi.index_all() == 2
    res = vi.search("字节的岗位", top_k=2)
    assert len(res) >= 1


def test_memory_search_tool_stub() -> None:
    t = make_memory_search_tool(None)
    out = t.invoke({"query": "RAG 面试题", "top_k": 3})
    assert "stub" in out


def test_memory_search_tool_real(tmp_path, valid_config_data: dict) -> None:
    settings = _settings(valid_config_data)
    em = EpisodicMemory(tmp_path / "t.jsonl")
    em.write(MemoryEntry(type="interview_qa", content={"q": "讲讲 RAG 检索流程", "a": "query->召回->rerank", "score": 8}))
    em.write(MemoryEntry(type="application", content={"company": "字节", "status": "submitted"}))
    vi = VectorIndex(FakeEmbedding(settings), FakeVectorStore(settings), em)
    vi.index_all()
    t = make_memory_search_tool(vi)
    out = t.invoke({"query": "字节投递", "top_k": 5})
    assert "application" in out or "interview_qa" in out
