"""L3 自建 trace 测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from careercrew_ai.react.react_loop import ReactLoop
from careercrew_core.tracing.trace import TraceRecorder


def test_trace_recorder(tmp_path) -> None:
    tr = TraceRecorder(tmp_path / "traces.jsonl")
    tr.agent_loop(agent="job_matcher", iteration=0, content="思考", tool_calls=["search_jobs"], tool_calls_total=1)
    tr.hitl(action="投递", decision="denied")
    tr.memory_op(op="write", entry_id="e_1", type="job_match")
    tr.compaction(first_kept_entry_id="e_1", kept=5, compressed=10)
    traces = tr.read_all()
    assert len(traces) == 4
    assert traces[0]["trace_type"] == "agent_loop"
    assert traces[1]["trace_type"] == "hitl"
    assert traces[2]["trace_type"] == "memory_op"
    assert traces[3]["trace_type"] == "compaction"


def test_react_loop_with_tracer(tmp_path) -> None:
    tr = TraceRecorder(tmp_path / "traces.jsonl")

    class FakeLLM:
        def bind_tools(self, tools, **kwargs):
            return self

        def invoke(self, messages, config=None):
            return AIMessage(content="最终答案")

    loop = ReactLoop(max_iterations=3, tracer=tr)
    loop.run("sys", [HumanMessage(content="hi")], [], FakeLLM())
    traces = tr.read_all()
    assert len(traces) == 1
    assert traces[0]["trace_type"] == "agent_loop"
    assert traces[0]["agent"] == "react"
