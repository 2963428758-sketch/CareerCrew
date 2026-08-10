"""L4/L5 Dashboard 数据 helper 冒烟测试（Streamlit 页面已退役）。"""
from __future__ import annotations

from careercrew_ui.dashboard.data import (
    get_episodic_entries,
    get_settings_summary,
    get_user_model,
)


def test_settings_summary() -> None:
    cfg = get_settings_summary()
    assert "llm" in cfg
    assert "vector_store" in cfg


def test_empty_data_helpers() -> None:
    assert get_episodic_entries("nonexistent.jsonl") == []


def test_user_model_default() -> None:
    m = get_user_model(user_id="u_001", path="data/nonexistent_um.json")
    assert m["user_id"] == "u_001"

