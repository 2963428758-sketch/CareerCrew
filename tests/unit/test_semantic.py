"""语义记忆（SemanticFactStore）+ profile_update 工具测试。"""
from __future__ import annotations

import pytest

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.semantic import SemanticFactStore
from careercrew_core.tools.internal.profile_update import make_profile_update_tool


def _store(user_id: str = "u1") -> SemanticFactStore:
    return SemanticFactStore(FakeMemoryDb(), user_id=user_id)


def test_load_default() -> None:
    m = _store().load("u1")
    assert m.user_id == "u1"
    assert m.profile.skills == []


def test_update_and_persist() -> None:
    store = _store()
    m = store.update("u1", {
        "profile.skills": ["Python", "RAG"],
        "target_companies": ["字节跳动"],
        "preferences.salary_min": 30,
    })
    assert m.profile.skills == ["Python", "RAG"]
    assert m.target_companies == ["字节跳动"]
    assert m.preferences.salary_min == 30
    m2 = store.load("u1")
    assert m2.profile.skills == ["Python", "RAG"]


def test_update_illegal_field_rejected() -> None:
    store = _store()
    with pytest.raises(ValueError):
        store.update("u1", {"profile.evil": "x"})
    with pytest.raises(ValueError):
        store.update("u1", {"bad_field": "x"})


def test_profile_update_tool_writes() -> None:
    store = _store()
    t = make_profile_update_tool(store, user_id="u1", source="test")
    out = t.invoke({"fields": {"profile.skills": ["RAG"], "profile.level": "中级"}})
    assert "更新成功" in out
    m = store.load("u1")
    assert m.profile.skills == ["RAG"]
    assert m.profile.level == "中级"
    # 事实带来源
    f = store.get_fact("profile.skills")
    assert f.source == "test"
    assert f.version == 1


def test_profile_update_tool_rejects_illegal() -> None:
    store = _store()
    t = make_profile_update_tool(store, user_id="u1")
    out = t.invoke({"fields": {"bad": "x"}})
    assert "[error]" in out
    assert "非法字段" in out


def test_fact_version_increments_on_conflict() -> None:
    store = _store()
    store.upsert_fact("preferences.salary_min", "preference", {"salary_min": 30}, source="a")
    store.upsert_fact("preferences.salary_min", "preference", {"salary_min": 25}, source="b")
    f = store.get_fact("preferences.salary_min")
    assert f.version == 2
    assert f.content == {"salary_min": 25}
    assert f.source == "b"


def test_delete_fact() -> None:
    store = _store()
    store.upsert_fact("profile.skills", "profile", {"skills": ["Python"]}, source="t")
    assert store.delete_fact("profile.skills") == 1
    assert store.get_fact("profile.skills") is None
