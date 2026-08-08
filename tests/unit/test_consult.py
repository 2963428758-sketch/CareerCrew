"""M3 多 agent 会诊测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.supervisor.consult import build_consult_graph, consult


class FakeAgent:
    def __init__(self, name: str, content: str) -> None:
        self._name = name
        self._content = content
        self.last_result = type("R", (), {"content": content})()

    def run(self, state) -> dict:
        # LangGraph 节点：返回 state 更新（agent_outputs 由 merge_dicts 合并）
        return {"agent_outputs": {self._name: {"content": self._content}}}


def _mk_agents() -> dict:
    return {
        "salary_negotiator": FakeAgent("salary_negotiator", "建议 35K，有 offer 竞争可抬"),
        "career_planner": FakeAgent("career_planner", "字节是冲刺梯队，可接"),
    }


def test_consult_function() -> None:
    class FakeLLM:
        def invoke(self, prompt):
            return AIMessage(content="综合：都建议投字节，共识明确")

    agents = _mk_agents()
    out = consult(agents, "这个字节 offer 要不要接", FakeLLM())
    assert "salary_negotiator" in out["opinions"]
    assert "career_planner" in out["opinions"]
    assert out["synthesis"] == "综合：都建议投字节，共识明确"


def test_consult_graph_parallel_fanout_join() -> None:
    """LangGraph fan-out + join：多个 agent 并行后综合。"""
    class FakeLLM:
        def invoke(self, prompt):
            return AIMessage(content="综合意见：建议接")

    agents = _mk_agents()
    app = build_consult_graph(agents, FakeLLM())
    init = {
        "thread_id": "c1", "user_id": "u1", "stage": "review",
        "user_intent": "这个字节 offer 要不要接",
        "messages": [HumanMessage(content="这个字节 offer 要不要接")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    result = app.invoke(init)
    assert "综合意见" in result["synthesis"]
    # 两个 agent 的产出都被合并进 agent_outputs（fan-out 并行）
    assert "salary_negotiator" in result["agent_outputs"]
    assert "career_planner" in result["agent_outputs"]
