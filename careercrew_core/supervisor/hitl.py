"""HITL interrupt 与恢复（K2）。

LangGraph interrupt 暂停图执行，等人确认（CLI yes/no），Command(resume=...) 恢复。
高风险工具（K1 标记 requires_confirmation）触发时调用。
"""
from __future__ import annotations

from langgraph.types import Command, interrupt


def interrupt_for_confirmation(action: dict) -> dict:
    """暂停图执行等人工确认。action: {type, description, ...}。返回用户决策。"""
    return interrupt({"type": "hitl_confirm", "action": action})


def resume(decision: dict) -> Command:
    """恢复图执行。decision: {confirmed: bool, reason: str, ...}。"""
    return Command(resume=decision)
