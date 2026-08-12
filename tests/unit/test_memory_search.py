"""情景记忆向量索引 + memory_search 融合检索测试（Fake 后端）。"""
from __future__ import annotations

from careercrew_ai.embedding import FakeEmbedding
from careercrew_ai.vector_store import FakeVectorStore
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.router import MemoryRouter
from careercrew_core.memory.semantic import SemanticFactStore
from careercrew_core.memory.types import MemoryEntry
from careercrew_core.memory.vector_index import VectorIndex
from careercrew_core.state.settings import Settings
from careercrew_core.tools.internal.memory_search import make_memory_search_tool


def _settings(valid_config_data: dict) -> Settings:
    valid_config_data["embedding"]["provider"] = "fake"
    valid_config_data["vector_store"]["backend"] = "fake"
    return Settings.model_validate(valid_config_data)


def test_vector_index_roundtrip(valid_config_data: dict) -> None:
    settings = _settings(valid_config_data)
    db = FakeMemoryDb()
    em = EpisodicMemory(db, user_id="u1", thread_id="t1")
    em.write(MemoryEntry(type="interview_qa", content={"q": "RAG 怎么减幻觉", "score": 8}))
    em.write(MemoryEntry(type="job_match", content={"company": "字节", "score": 0.9}))
    vi = VectorIndex(FakeEmbedding(settings), FakeVectorStore(settings), em, user_id="u1")
    assert vi.index_all() == 2
    res = vi.search("字节的岗位", top_k=2)
    assert len(res) >= 1


def test_memory_search_tool_stub() -> None:
    t = make_memory_search_tool()
    out = t.invoke({"query": "RAG 面试题", "top_k": 3})
    assert "stub" in out


def test_memory_search_tool_real(valid_config_data: dict) -> None:
    settings = _settings(valid_config_data)
    db = FakeMemoryDb()
    em = EpisodicMemory(db, user_id="u1", thread_id="t1")
    em.write(MemoryEntry(type="interview_qa", content={"q": "讲讲 RAG 检索流程", "a": "query->召回->rerank", "score": 8}))
    em.write(MemoryEntry(type="application", content={"company": "字节", "status": "submitted"}))
    vi = VectorIndex(FakeEmbedding(settings), FakeVectorStore(settings), em, user_id="u1")
    vi.index_all()
    facts = SemanticFactStore(db, user_id="u1")
    facts.upsert_fact("preferences.city", "preference", {"city": ["北京"]}, source="test")
    t = make_memory_search_tool(vi, fact_store=facts, router=MemoryRouter())
    out = t.invoke({"query": "字节投递", "top_k": 5})
    assert "application" in out or "interview_qa" in out


def test_memory_search_returns_facts(valid_config_data: dict) -> None:
    db = FakeMemoryDb()
    facts = SemanticFactStore(db, user_id="u1")
    facts.upsert_fact(
        "preferences.salary_min", "preference",
        {"salary_min": 30}, description="薪资预期 30K", source="test",
    )
    t = make_memory_search_tool(fact_store=facts, router=MemoryRouter())
    out = t.invoke({"query": "薪资预期", "top_k": 5})
    assert "fact:preference" in out
    assert "30" in out
