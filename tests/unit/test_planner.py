"""J3 职业规划师测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.agents.career_planner import CareerPlanner
from careercrew_core.memory.user_model import UserModelStore
from careercrew_core.tools.internal.profile_update import make_profile_update_tool
from careercrew_core.tools.registry import ToolRegistry, ToolSpec
from tests.fakes import FakeChatModel


def test_planner_updates_profile(tmp_path) -> None:
    um = UserModelStore(tmp_path / "um.json")
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=make_profile_update_tool(um, user_id="u1")))
    agent = CareerPlanner(
        llm=FakeChatModel([
            AIMessage(content="", tool_calls=[
                {"name": "profile_update", "args": {"fields": {"profile.skills": ["Python", "RAG"], "profile.direction": "大模型应用"}}, "id": "c1", "type": "tool_call"}
            ]),
            AIMessage(content="规划完成：冲刺字节/阿里，匹配美团/腾讯，阶段 0-3 月补 RAG 深度"),
        ]),
        tools=reg, max_iterations=5,
    )
    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "planning", "user_intent": "帮我做职业规划",
        "messages": [HumanMessage(content="我是 Python 方向，想做 Agent 应用，帮我规划")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)
    assert "规划完成" in agent.last_result.content
    # profile_update 已结构化写入
    model = um.load("u1")
    assert "Python" in model.profile.skills
    assert model.profile.direction == "大模型应用"
