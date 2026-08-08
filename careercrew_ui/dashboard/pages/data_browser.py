"""数据浏览页面（L4）：User Model / 情景记忆树 / 候选数据。"""
from __future__ import annotations

import streamlit as st

from careercrew_ui.dashboard.data import get_episodic_entries, get_user_model


def render() -> None:
    st.title("数据浏览")
    st.subheader("User Model")
    try:
        st.json(get_user_model())
    except Exception as e:
        st.warning(f"User Model 未初始化: {e}")

    st.subheader("情景记忆（append-only 树）")
    entries = get_episodic_entries()
    if not entries:
        st.info("暂无情景记忆")
        return
    for e in entries:
        st.write(f"`{e['id']}` (parent={e['parentId']}) `{e['type']}`: {e['content']}")
