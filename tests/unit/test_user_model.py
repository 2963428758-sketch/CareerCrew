"""C5 长期 User Model 读写 + profile_update 工具测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from careercrew_core.memory.user_model import UserModelStore
from careercrew_core.tools.internal.profile_update import make_profile_update_tool


def test_load_default(tmp_path: Path) -> None:
    store = UserModelStore(tmp_path / "um.json")
    m = store.load("u1")
    assert m.user_id == "u1"
    assert m.profile.skills == []


def test_update_and_persist(tmp_path: Path) -> None:
    store = UserModelStore(tmp_path / "um.json")
    m = store.update("u1", {
        "profile.skills": ["Python", "RAG"],
        "target_companies": ["字节跳动"],
        "preferences.salary_min": 30,
    })
    assert m.profile.skills == ["Python", "RAG"]
    assert m.target_companies == ["字节跳动"]
    assert m.preferences.salary_min == 30
    # 重新 load 验证持久化
    m2 = store.load("u1")
    assert m2.profile.skills == ["Python", "RAG"]


def test_update_illegal_field_rejected(tmp_path: Path) -> None:
    store = UserModelStore(tmp_path / "um.json")
    with pytest.raises(ValueError):
        store.update("u1", {"profile.evil": "x"})
    with pytest.raises(ValueError):
        store.update("u1", {"bad_field": "x"})


def test_profile_update_tool_writes(tmp_path: Path) -> None:
    store = UserModelStore(tmp_path / "um.json")
    t = make_profile_update_tool(store, user_id="u1")
    out = t.invoke({"fields": {"profile.skills": ["RAG"], "profile.level": "中级"}})
    assert "更新成功" in out
    m = store.load("u1")
    assert m.profile.skills == ["RAG"]
    assert m.profile.level == "中级"


def test_profile_update_tool_rejects_illegal(tmp_path: Path) -> None:
    store = UserModelStore(tmp_path / "um.json")
    t = make_profile_update_tool(store, user_id="u1")
    out = t.invoke({"fields": {"bad": "x"}})
    assert "[error]" in out
    assert "非法字段" in out
