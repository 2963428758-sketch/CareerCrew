"""L4/L5 Dashboard 冒烟测试（数据 helper + 页面可导入）。"""
from __future__ import annotations

from careercrew_ui.dashboard.data import (
    get_episodic_entries,
    get_settings_summary,
    get_traces,
    get_user_model,
)


def test_settings_summary() -> None:
    cfg = get_settings_summary()
    assert "llm" in cfg
    assert "vector_store" in cfg


def test_empty_data_helpers() -> None:
    assert get_episodic_entries("nonexistent.jsonl") == []
    assert get_traces("nonexistent.jsonl") == []


def test_user_model_default() -> None:
    m = get_user_model(user_id="u_001", path="data/nonexistent_um.json")
    assert m["user_id"] == "u_001"


def test_dashboard_pages_importable() -> None:
    from careercrew_ui.dashboard import app as _app  # noqa: F401
    from careercrew_ui.dashboard.pages import data_browser, overview, traces  # noqa: F401

    assert hasattr(overview, "render")
    assert hasattr(data_browser, "render")
    assert hasattr(traces, "render")
