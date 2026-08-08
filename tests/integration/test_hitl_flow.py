"""K2/K3 HITL interrupt + 闸门测试。"""
from __future__ import annotations

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from typing import TypedDict

from careercrew_cli.hitl.gates import HitlGates
from careercrew_core.supervisor.hitl import interrupt_for_confirmation
from careercrew_ui.cli.renderer import Renderer


class HState(TypedDict):
    decision: dict


def _hitl_node(state: HState) -> dict:
    decision = interrupt_for_confirmation({"type": "apply", "description": "投递字节"})
    return {"decision": decision}


@pytest.mark.integration
def test_langgraph_interrupt_and_resume() -> None:
    """interrupt 暂停 -> 拿决策 -> Command(resume) 恢复（需 checkpointer）。"""
    from langgraph.checkpoint.memory import MemorySaver

    g = StateGraph(HState)
    g.add_node("hitl", _hitl_node)
    g.add_edge(START, "hitl")
    g.add_edge("hitl", END)
    app = g.compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}

    # 第一次 invoke：触发 interrupt，返回 __interrupt__
    result = app.invoke({"decision": None}, config=cfg)
    assert result.get("__interrupt__"), "应触发 interrupt"

    # 用 Command(resume) 恢复
    resumed = app.invoke(Command(resume={"confirmed": True}), config=cfg)
    assert resumed["decision"] == {"confirmed": True}


def test_gates_default_deny() -> None:
    gates = HitlGates(renderer=Renderer(), input_fn=lambda _: "")  # 回车=默认拒绝
    assert gates.gate_apply("字节", "大模型工程师") is False
    assert gates.gate_offer("字节", "35K") is False
    assert gates.gate_greeting("字节") is False
    assert gates.gate_salary_talk("字节") is False


def test_gates_confirm_yes() -> None:
    gates = HitlGates(renderer=Renderer(), input_fn=lambda _: "y")
    assert gates.gate_apply("字节", "大模型工程师") is True
