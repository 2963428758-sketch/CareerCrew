"""追踪查看页面（L4）：agent ReAct 轨迹 / HITL 历史 / 记忆检索命中。"""
from __future__ import annotations

import streamlit as st

from careercrew_ui.dashboard.data import get_traces


def render() -> None:
    st.title("追踪查看")
    traces = get_traces()
    if not traces:
        st.info("暂无 trace 数据（跑一次 agent 后可见）")
        return
    st.write(f"共 {len(traces)} 条 trace")
    by_type: dict[str, int] = {}
    for t in traces:
        by_type[t.get("trace_type", "?")] = by_type.get(t.get("trace_type", "?"), 0) + 1
    st.write(by_type)
    for t in traces:
        st.code(t, language="json")
