"""投递/打招呼/接 offer mock 工具（K1）：高风险动作，requires_confirmation=True。"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from careercrew_core.tools.registry import ToolRegistry, ToolSpec


@tool
def submit_application(company: str, title: str, resume: str = "") -> str:
    """投递简历（高风险，需人工确认）。"""
    return f"已投递 {company} {title}"


@tool
def send_greeting(company: str, message: str = "") -> str:
    """给 HR / 猎头发打招呼消息（高风险，需人工确认）。"""
    return f"已发送打招呼给 {company}"


@tool
def accept_offer(company: str, salary: str = "") -> str:
    """接受 offer（高风险，需人工确认）。"""
    return f"已接受 {company} offer（{salary}）"


@tool
def salary_talk_script(company: str, target_salary: str = "") -> str:
    """谈薪话术草稿（高风险，需确认后才发送）。"""
    return f"谈薪话术: 目标 {target_salary} @ {company}"


# 高风险工具清单（HITL 必确认）
HIGH_RISK_TOOLS: list[BaseTool] = [submit_application, send_greeting, accept_offer, salary_talk_script]


def register_high_risk_tools(registry: ToolRegistry) -> None:
    """把高风险工具注册进 registry（requires_confirmation=True，K 阶段接 interrupt）。"""
    for t in HIGH_RISK_TOOLS:
        registry.register(ToolSpec(tool=t, source="internal", requires_confirmation=True))
