"""T1.4 agent 层观测中间件测试：token 累计 + tool 计时/错误记录（TDD）。

覆盖：
- UsageAccumulatorMiddleware 从 usage_metadata 累计 input/output tokens（容错缺失）
- ObservabilityMiddleware.wrap_tool_call 计时（duration_ms）并记录 (name, args, error)
- AgentResult 新字段 input_tokens/output_tokens/tool_call_details 与契约老字段共存
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from careercrew_ai.agents.langchain_agent import (
    AgentResult,
    ObservabilityMiddleware,
    UsageAccumulatorMiddleware,
    build_agent,
    run_agent,
)
from careercrew_core.agents.base_agent import BaseAgent
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


def _msg(content="", tool_calls=None, usage=None):
    kwargs = {"content": content}
    if tool_calls:
        kwargs["tool_calls"] = tool_calls
    if usage is not None:
        kwargs["usage_metadata"] = usage
    return AIMessage(**kwargs)


# ── UsageAccumulatorMiddleware 单元 ──


def test_usage_middleware_accumulates_tokens() -> None:
    mw = UsageAccumulatorMiddleware()
    assert mw.input_tokens == 0
    assert mw.output_tokens == 0

    mw._add_usage({"input_tokens": 100, "output_tokens": 50, "total_tokens": 150})
    mw._add_usage({"input_tokens": 30, "output_tokens": 20, "total_tokens": 50})

    assert mw.input_tokens == 130
    assert mw.output_tokens == 70


def test_usage_middleware_tolerates_missing_keys() -> None:
    mw = UsageAccumulatorMiddleware()
    mw._add_usage({})  # 空 dict 不报错
    mw._add_usage(None)  # None 不报错
    assert mw.input_tokens == 0
    assert mw.output_tokens == 0


def test_usage_middleware_snapshot() -> None:
    mw = UsageAccumulatorMiddleware()
    mw._add_usage({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    snap = mw.snapshot()
    assert snap == (10, 5)
    # 快照不影响后续累计
    mw._add_usage({"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
    assert mw.input_tokens == 11


def test_usage_middleware_snapshot_no_usage_is_none() -> None:
    """从未观测到 usage 时 snapshot 返回 (None, None)。"""
    mw = UsageAccumulatorMiddleware()
    assert mw.snapshot() == (None, None)


def test_usage_middleware_snapshot_preserves_zero() -> None:
    """观测到 usage（即使 0）后 snapshot 返回 (0, 0)，不被 or None 折叠。"""
    mw = UsageAccumulatorMiddleware()
    mw._add_usage({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    assert mw.snapshot() == (0, 0)


# ── ObservabilityMiddleware 单元（tool 计时） ──


def test_observability_middleware_times_tool_call() -> None:
    mw = ObservabilityMiddleware()
    req = type("R", (), {"tool_call": _tc("add", {"a": 2, "b": 3})})()
    handler = lambda r: type("Msg", (), {"content": "5"})()  # noqa: E731
    mw.wrap_tool_call(req, handler)
    assert len(mw.tool_call_details) == 1
    detail = mw.tool_call_details[0]
    assert detail["name"] == "add"
    assert detail["args"] == {"a": 2, "b": 3}
    assert detail["duration_ms"] >= 0
    assert detail["error"] is None


def test_observability_middleware_records_tool_error() -> None:
    mw = ObservabilityMiddleware()
    req = type("R", (), {"tool_call": _tc("boom", {"x": 1})})()

    def handler(r):
        raise ValueError("工具炸了")

    try:
        mw.wrap_tool_call(req, handler)
    except ValueError:
        pass
    assert len(mw.tool_call_details) == 1
    detail = mw.tool_call_details[0]
    assert detail["name"] == "boom"
    assert detail["error"] is not None
    assert "工具炸了" in detail["error"]


# ── AgentResult 新字段 + build_agent/run_agent 集成 ──


def test_agent_result_new_fields_default_none() -> None:
    r = AgentResult(content="x", iterations=[], tool_calls_total=0, stopped_reason="final_answer")
    assert r.input_tokens is None
    assert r.output_tokens is None
    assert r.tool_call_details == []


def test_run_agent_populates_tokens_and_tool_details() -> None:
    """真跑 create_agent：tool 调用后最终答案，中途的 usage_metadata 被累计、
    工具计时被记录到 AgentResult 新字段。"""
    llm = FakeChatModel([
        _msg("", tool_calls=[_tc("add", {"a": 2, "b": 3})],
             usage={"input_tokens": 120, "output_tokens": 8, "total_tokens": 128}),
        _msg("5", usage={"input_tokens": 200, "output_tokens": 6, "total_tokens": 206}),
    ])
    from careercrew_api.chat_lifecycle import TurnContext  # noqa: F401  # 确认无循环导入

    agent = build_agent(
        llm=llm, tools=[add], system_prompt="sys", max_iterations=5,
    )
    result = run_agent(agent, [HumanMessage(content="2+3")])

    assert result.content == "5"
    assert result.input_tokens == 320  # 120 + 200
    assert result.output_tokens == 14  # 8 + 6
    assert len(result.tool_call_details) == 1
    assert result.tool_call_details[0]["name"] == "add"
    # 老字段不受影响
    assert result.tool_calls_total == 1
    assert len(result.iterations) == 2


def test_run_agent_zero_tokens_preserved() -> None:
    """模型上报 usage_metadata 且 input_tokens=0 时，input_tokens==0（非 None）。"""
    llm = FakeChatModel([
        _msg("hello", usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}),
    ])
    agent = build_agent(llm=llm, tools=None, system_prompt="sys", max_iterations=5)
    result = run_agent(agent, [HumanMessage(content="hi")])
    assert result.content == "hello"
    assert result.input_tokens == 0
    assert result.output_tokens == 0


def test_run_agent_no_usage_tokens_none() -> None:
    """FakeChatModel 无 usage_metadata 时 tokens 保持 None（静默降级）。"""
    llm = FakeChatModel([AIMessage(content="无工具回答")])
    agent = build_agent(llm=llm, tools=None, system_prompt="sys", max_iterations=5)
    result = run_agent(agent, [HumanMessage(content="hi")])
    assert result.content == "无工具回答"
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.tool_call_details == []
