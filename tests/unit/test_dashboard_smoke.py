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


def test_empty_data_helpers(tmp_path) -> None:
    # 用 tmp_path 而非 CWD 相对路径，避免 EpisodicMemory touch 出仓库根的空 jsonl
    assert get_episodic_entries(str(tmp_path / "empty.jsonl")) == []


def test_user_model_default() -> None:
    m = get_user_model(user_id="u_001", path="data/nonexistent_um.json")
    assert m["user_id"] == "u_001"
