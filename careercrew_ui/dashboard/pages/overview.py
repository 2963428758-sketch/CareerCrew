"""系统总览页面（L4）。"""
from __future__ import annotations

import streamlit as st

from careercrew_ui.dashboard.data import get_episodic_entries, get_settings_summary


def render() -> None:
    st.title("系统总览")
    st.subheader("组件配置")
    st.json(get_settings_summary())

    entries = get_episodic_entries()
    st.subheader("记忆统计")
    st.write(f"情景记忆条目数：{len(entries)}")
    types: dict[str, int] = {}
    for e in entries:
        types[e["type"]] = types.get(e["type"], 0) + 1
    st.write(types)
