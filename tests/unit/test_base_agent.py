"""B4 agent 节点基类测试（create_agent 执行链，AGENT_LANGSMITH_SPEC Part A）。

覆盖 A4 用例清单：工具执行→最终答案 / max_iterations 短路 / 无工具直答 /
流式 token 回调 / 工具异常回喂 / ToolRegistry 绑定。
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from careercrew_core.agents.base_agent import BaseAgent
from careercrew_core.tools.registry import ToolRegistry, ToolSpec
from tests.fakes import FakeChatModel


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool
def boom(x: int) -> int:
    """Always raises."""
    raise ValueError("工具炸了")


def _tc(name: str, args: dict, id_: str = "c1") -> dict:
    return {"name": name, "args": args, "id": id_, "type": "tool_call"}


def _state(**overrides):
    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "match", "user_intent": "",
        "messages": [HumanMessage(content="hi")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    state.update(overrides)
    return state


def test_tool_call_then_final() -> None:
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("add", {"a": 2, "b": 3})]),
        AIMessage(content="5"),
    ])
    agent = BaseAgent(name="job_matcher", system_prompt="你是匹配官", llm=llm, tools=[add])
    update = agent.run(_state())
    # messages：追加 AIMessage
    assert len(update["messages"]) == 1
    assert isinstance(update["messages"][0], AIMessage)
    assert update["messages"][0].content == "5"
    # agent_outputs：写到 [name]
    out = update["agent_outputs"]["job_matcher"]
    assert out["content"] == "5"
    assert out["stopped_reason"] == "final_answer"
    assert out["tool_calls_total"] == 1
    assert out["iterations"] == 2
    # last_result：迭代明细（轻量）+ 工具结果回喂
    assert agent.last_result is not None
    assert len(agent.last_result.iterations) == 2
    assert agent.last_result.iterations[0].tool_calls[0]["name"] == "add"
    assert agent.last_result.iterations[0].tool_results == ["5"]
    assert agent.last_result.iterations[1].tool_calls == []


def test_max_iterations_short_circuit() -> None:
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("add", {"a": 1, "b": 1}, f"c{i}")])
        for i in range(10)
    ])
    agent = BaseAgent(name="x", system_prompt="sys", llm=llm, tools=[add], max_iterations=3)
    update = agent.run(_state())
    out = update["agent_outputs"]["x"]
    assert out["stopped_reason"] == "max_iterations"
    assert out["iterations"] == 3
    assert out["tool_calls_total"] == 3
    assert agent.last_result.content == "（已达最大迭代轮次）"


def test_max_iterations_short_circuit_high_limit() -> None:
    """回归：langchain 1.3 的 before_model 是独立图节点，每轮迭代消耗 3 个
    super-step。N=10 时 marker 需约 32 个 super-step，旧 recursion_limit
    （2*N+6=26）会先撞 GraphRecursionError → 空 content。"""
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("add", {"a": 1, "b": 1}, f"c{i}")])
        for i in range(12)
    ])
    agent = BaseAgent(name="x", system_prompt="sys", llm=llm, tools=[add], max_iterations=10)
    update = agent.run(_state())
    out = update["agent_outputs"]["x"]
    assert out["stopped_reason"] == "max_iterations"
    assert out["iterations"] == 10
    assert out["tool_calls_total"] == 10
    assert agent.last_result.content == "（已达最大迭代轮次）"


def test_no_tools_direct_answer() -> None:
    llm = FakeChatModel([AIMessage(content="无工具回答")])
    agent = BaseAgent(name="x", system_prompt="sys", llm=llm)
    update = agent.run(_state())
    out = update["agent_outputs"]["x"]
    assert out["content"] == "无工具回答"
    assert out["stopped_reason"] == "final_answer"
    assert out["tool_calls_total"] == 0
    assert out["iterations"] == 1


def test_streaming_token_callback() -> None:
    tokens: list[str] = []
    llm = FakeChatModel([AIMessage(content="流式输出测试")])
    agent = BaseAgent(
        name="x", system_prompt="sys", llm=llm,
        stream_callback=lambda t: tokens.append(t),
    )
    update = agent.run(_state())
    assert "".join(tokens) == "流式输出测试"
    assert update["agent_outputs"]["x"]["content"] == "流式输出测试"
    assert update["agent_outputs"]["x"]["stopped_reason"] == "final_answer"


def test_tool_error_fed_back() -> None:
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("boom", {"x": 1})]),
        AIMessage(content="我处理了错误"),
    ])
    agent = BaseAgent(name="x", system_prompt="sys", llm=llm, tools=[boom])
    update = agent.run(_state())
    out = update["agent_outputs"]["x"]
    assert out["content"] == "我处理了错误"
    assert out["stopped_reason"] == "final_answer"
    assert out["tool_calls_total"] == 1
    assert str(agent.last_result.iterations[0].tool_results[0]).startswith("Error:")


def test_with_tool_registry() -> None:
    llm = FakeChatModel([AIMessage(content="done")])
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=add))
    agent = BaseAgent(name="planner", system_prompt="sys", llm=llm, tools=reg)
    update = agent.run(_state(stage="planning"))
    assert update["agent_outputs"]["planner"]["content"] == "done"
    assert update["agent_outputs"]["planner"]["stopped_reason"] == "final_answer"
