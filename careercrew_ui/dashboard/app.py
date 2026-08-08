"""Streamlit Dashboard 入口（L4）。跑法：conda run -n careercrew streamlit run careercrew_ui/dashboard/app.py"""
from __future__ import annotations

import streamlit as st

from careercrew_ui.dashboard.pages.data_browser import render as render_data
from careercrew_ui.dashboard.pages.overview import render as render_overview
from careercrew_ui.dashboard.pages.traces import render as render_traces

st.set_page_config(page_title="CareerCrew Dashboard", layout="wide")
page = st.sidebar.radio("页面", ["系统总览", "数据浏览", "追踪查看"])
if page == "系统总览":
    render_overview()
elif page == "数据浏览":
    render_data()
else:
    render_traces()
