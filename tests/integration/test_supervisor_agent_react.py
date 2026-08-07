"""B 阶段集成：supervisor + BaseAgent + ReAct + 工具注册表 端到端。

验证 DEV_SPEC 4.2.2 的「supervisor + agent + ReAct」协作：
supervisor 路由到 BaseAgent -> ReAct 循环调工具 -> 产出写回 state -> 推进 stage 终止。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from careercrew_core.agents.base_agent import BaseAgent
from careercrew_core.state.checkpointer import get_checkpointer
from careercrew_core.state.settings import Settings
from careercrew_core.supervisor.graph import build_graph
from careercrew_core.tools.registry import ToolRegistry, ToolSpec


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


class FakeChatModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self._i = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages, config=None):
        resp = self.responses[self._i]
        self._i += 1
        return resp


def _tc(name, args, id_="1"):
    return {"name": name, "args": args, "id": id_, "type": "tool_call"}


@pytest.mark.integration
def test_supervisor_agent_react_integration(tmp_path: Path, valid_config_data: dict) -> None:
    """supervisor 路由 -> BaseAgent 跑 ReAct（调工具）-> 产出写回 state -> 终止。"""
    valid_config_data["supervisor"]["checkpointer"]["path"] = str(tmp_path / "cp.db")
    settings = Settings.model_validate(valid_config_data)
    cp = get_checkpointer(settings)

    # career_planner agent：调 add 工具算 1+2，然后把 stage 推到 apply 终止
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("add", {"a": 1, "b": 2}, "c1")]),
        AIMessage(content="规划完成，1+2=3"),
    ])
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=add))

    class PlannerAgent(BaseAgent):
        def run(self, state):
            update = super().run(state)
            update["stage"] = "apply"  # 推进到 HITL 闸门终止
            return update

    planner = PlannerAgent(name="career_planner", system_prompt="你是规划师", llm=llm, tools=reg)

    app = build_graph({"career_planner": planner.run}, checkpointer=cp)
    init = {
        "thread_id": "t1", "user_id": "u1", "stage": "intent", "user_intent": "找工作",
        "messages": [HumanMessage(content="开始规划")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    result = app.invoke(init, config={"configurable": {"thread_id": "t1"}})

    # stage 推到 apply（终止）
    assert result["stage"] == "apply"
    # agent_outputs 有 career_planner 产出（ReAct 调了一次工具）
    assert "career_planner" in result["agent_outputs"]
    assert result["agent_outputs"]["career_planner"]["tool_calls_total"] == 1
    assert result["agent_outputs"]["career_planner"]["stopped_reason"] == "final_answer"
    # messages 含最终答案
    contents = [getattr(m, "content", "") for m in result["messages"]]
    assert "规划完成" in " ".join(contents)
