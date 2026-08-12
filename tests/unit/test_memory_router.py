"""LLM 记忆路由测试（选择 top-N + 失败回退）。"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.router import MemoryRouter
from careercrew_core.memory.semantic import SemanticFactStore


def _facts() -> list:
    db = FakeMemoryDb()
    s = SemanticFactStore(db, user_id="u1")
    s.upsert_fact("profile.skills", "profile", {"skills": ["Python", "RAG"]},
                  description="技能 Python/RAG", source="t")
    s.upsert_fact("preferences.salary_min", "preference", {"salary_min": 30},
                  description="薪资预期 30K", source="t")
    s.upsert_fact("preferences.city", "preference", {"city": ["北京"]},
                  description="城市北京", source="t")
    return s.list_facts()


def test_llm_select_top_n() -> None:
    class FakeLLM:
        def invoke(self, prompt):
            return AIMessage(content="[1, 0]")

    facts = _facts()
    picked = MemoryRouter(llm=FakeLLM(), top_n=2).select("薪资与技能", facts)
    assert len(picked) == 2
    # 严格遵循 LLM 返回的序号（facts[1] 在前、facts[0] 在后）
    assert picked[0].name == facts[1].name
    assert picked[1].name == facts[0].name


def test_fallback_on_bad_llm_output() -> None:
    class BadLLM:
        def invoke(self, prompt):
            return AIMessage(content="不是 JSON")

    facts = _facts()
    picked = MemoryRouter(llm=BadLLM(), top_n=3).select("北京 薪资", facts)
    assert len(picked) <= 3
    # 回退不抛异常且返回列表
    assert isinstance(picked, list)


def test_no_llm_keyword_fallback() -> None:
    facts = _facts()
    picked = MemoryRouter(top_n=3).select("薪资预期 30", facts)
    assert any("salary_min" in f.name for f in picked)


def test_empty_facts() -> None:
    assert MemoryRouter().select("q", []) == []
