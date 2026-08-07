"""B4 agent 节点基类测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from careercrew_core.agents.base_agent import BaseAgent
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


def test_base_agent_runs_and_writes_output() -> None:
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("add", {"a": 2, "b": 3}, "c1")]),
        AIMessage(content="5"),
    ])
    agent = BaseAgent(name="job_matcher", system_prompt="你是匹配官", llm=llm, tools=[add])
    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "match", "user_intent": "",
        "messages": [HumanMessage(content="算 2+3")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    update = agent.run(state)
    # messages：追加 AIMessage
    assert len(update["messages"]) == 1
    assert isinstance(update["messages"][0], AIMessage)
    assert update["messages"][0].content == "5"
    # agent_outputs：写到 [name]
    assert "job_matcher" in update["agent_outputs"]
    out = update["agent_outputs"]["job_matcher"]
    assert out["content"] == "5"
    assert out["stopped_reason"] == "final_answer"
    assert out["tool_calls_total"] == 1
    assert out["iterations"] == 2
    # last_result 保存完整 trace
    assert agent.last_result is not None
    assert len(agent.last_result.iterations) == 2


def test_base_agent_with_tool_registry() -> None:
    llm = FakeChatModel([AIMessage(content="done")])
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=add))
    agent = BaseAgent(name="planner", system_prompt="sys", llm=llm, tools=reg)
    state = {"messages": [HumanMessage(content="hi")], "agent_outputs": {}}
    update = agent.run(state)
    assert update["agent_outputs"]["planner"]["content"] == "done"
    assert update["agent_outputs"]["planner"]["stopped_reason"] == "final_answer"


def test_base_agent_no_tools() -> None:
    llm = FakeChatModel([AIMessage(content="无工具回答")])
    agent = BaseAgent(name="x", system_prompt="sys", llm=llm)
    state = {"messages": [HumanMessage(content="hi")], "agent_outputs": {}}
    update = agent.run(state)
    assert update["agent_outputs"]["x"]["tool_calls_total"] == 0
