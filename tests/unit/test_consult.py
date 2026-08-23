"""M3 多 agent 会诊测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.supervisor.consult import _synthesize, build_consult_graph, consult, opinion_fallback


class FakeAgent:
    def __init__(self, name: str, content: str) -> None:
        self._name = name
        self._content = content
        self.last_result = type("R", (), {"content": content})()

    def run(self, state) -> dict:
        # LangGraph 节点：返回 state 更新（agent_outputs 由 merge_dicts 合并）
        return {"agent_outputs": {self._name: {"content": self._content}}}


class FailingAgent:
    def __init__(self, name: str, stopped_reason: str) -> None:
        self._name = name
        self.last_result = type("R", (), {"content": "", "stopped_reason": stopped_reason})()

    def run(self, state) -> dict:
        return {}


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
    out = consult(agents, "这个字节 offer 要不要接", FakeLLM(), user_id="u1")
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


def test_opinion_fallback_empty_on_error() -> None:
    assert opinion_fallback("", "error") == "（该顾问本次执行出错，未能给出意见）"


def test_opinion_fallback_empty_on_max_iterations() -> None:
    assert opinion_fallback("", "max_iterations") == "（该顾问达到最大分析轮次，未能给出完整意见）"


def test_opinion_fallback_keeps_content() -> None:
    assert opinion_fallback("  有效意见  ", "final_answer") == "有效意见"
    assert opinion_fallback("部分内容", "error") == "部分内容"


def test_synthesis_prompt_prohibits_inventing_user_qualifications() -> None:
    class CapturingLLM:
        prompt = ""

        def invoke(self, prompt):
            self.prompt = prompt
            return AIMessage(content="综合建议")

    llm = CapturingLLM()
    _synthesize({"salary_negotiator": "缺少候选人技能信息"}, "期望 35k", llm)

    assert "不得补充或暗示用户拥有未提供的技能" in llm.prompt
    assert "第一人称谈判话术只能引用已给出的事实" in llm.prompt
    assert "我/您能为团队带来的技术贡献/价值" in llm.prompt


def test_consult_function_fallback_for_failed_agent() -> None:
    class FakeLLM:
        def invoke(self, prompt):
            return AIMessage(content="综合：见上")

    out = consult(
        {"salary_negotiator": FailingAgent("salary_negotiator", "error")},
        "这个 offer 要不要接",
        FakeLLM(),
        user_id="u1",
    )
    assert out["opinions"]["salary_negotiator"] == "（该顾问本次执行出错，未能给出意见）"
