"""C1 记忆核心数据类型测试。"""
from __future__ import annotations

from careercrew_core.memory.types import (
    MemoryEntry,
    TreeNode,
    UserPreferences,
    UserProfile,
    UserModel,
)


def test_memory_entry_serialize_roundtrip() -> None:
    e = MemoryEntry(
        id="e_001", type="interview_qa", ts="2026-07-30T00:00:00Z",
        content={"q": "什么是 RAG", "a": "检索增强生成", "score": 8},
    )
    e2 = MemoryEntry.model_validate_json(e.model_dump_json())
    assert e2.id == "e_001"
    assert e2.content["q"] == "什么是 RAG"


def test_memory_entry_id_ts_default_empty() -> None:
    e = MemoryEntry(type="note", content="x")
    assert e.id == ""
    assert e.ts == ""
    assert e.parentId is None


def test_user_model_defaults() -> None:
    m = UserModel(user_id="u1")
    assert m.profile.skills == []
    assert m.target_companies == []
    assert m.preferences.city == []
    assert m.interview_mastery == {}


def test_user_model_structured() -> None:
    m = UserModel(
        user_id="u1",
        profile=UserProfile(skills=["Python", "LangGraph"], level="中级", direction="大模型应用"),
        target_companies=["字节跳动", "阿里"],
        preferences=UserPreferences(salary_min=30, city=["北京", "上海"]),
        interview_mastery={"RAG": 0.8, "Agent": 0.6},
    )
    assert m.profile.skills == ["Python", "LangGraph"]
    assert m.preferences.salary_min == 30
    assert m.interview_mastery["RAG"] == 0.8


def test_tree_node() -> None:
    root_entry = MemoryEntry(id="e_001", type="session_start", ts="t", content="root")
    child_entry = MemoryEntry(id="e_002", parentId="e_001", type="note", ts="t", content="c")
    node = TreeNode(entry=root_entry, children=[TreeNode(entry=child_entry)])
    assert node.entry.id == "e_001"
    assert node.children[0].entry.id == "e_002"
