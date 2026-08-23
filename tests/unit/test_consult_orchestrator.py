"""会诊总调度官 LangGraph 测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.supervisor.consult_orchestrator import build_consult_orchestrator_graph


class FakeDecisionLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.index = 0

    def invoke(self, prompt):
        if self.index >= len(self.responses):
            raise AssertionError("orchestrator LLM called more times than expected")
        resp = self.responses[self.index]
        self.index += 1
        return AIMessage(content=resp)


class FakeAgent:
    def __init__(self, name: str, content: str) -> None:
        self.name = name
        self.content = content
        self.last_result = type("R", (), {
            "content": content,
            "stopped_reason": "final_answer",
            "input_tokens": 10,
            "output_tokens": 5,
            "tool_call_details": [],
        })()

    def run(self, state):
        return {
            "agent_outputs": {
                self.name: {
                    "content": self.content,
                    "stopped_reason": "final_answer",
                    "tool_calls_total": 0,
                    "iterations": 0,
                }
            }
        }


def _state(question: str = "这个 offer 要不要接"):
    return {
        "thread_id": "c1",
        "user_id": "u1",
        "stage": "consult",
        "user_intent": question,
        "messages": [HumanMessage(content=question)],
        "pending_action": None,
        "agent_outputs": {},
        "target_companies": [],
        "synthesis": "",
        "orchestrator_round": 0,
        "total_agent_calls": 0,
        "next_agents": [],
        "agent_tasks": {},
        "consult_calls": [],
        "pending_user_entry_id": None,
        "needs_user_input": False,
        "input_fields": [],
        "user_profile": "",
    }


def _run(decision_llm, max_rounds=3, max_group_size=3, max_total_calls=8):
    def agent_factory(name, cb):
        return FakeAgent(name, f"{name} 的意见")

    app = build_consult_orchestrator_graph(
        decision_llm,
        agent_factory,
        max_rounds=max_rounds,
        max_group_size=max_group_size,
        max_total_calls=max_total_calls,
    )
    return app.invoke(_state())


def test_parallel_group_then_finish() -> None:
    llm = FakeDecisionLLM([
        '{"next_agents": ["salary_negotiator", "career_planner"], "tasks": {}, "final_answer": ""}',
        '{"next_agents": [], "tasks": {}, "final_answer": "综合结论"}',
    ])
    result = _run(llm)
    assert result["synthesis"] == "综合结论"
    assert len(result["consult_calls"]) == 2
    assert {c["agent"] for c in result["consult_calls"]} == {
        "salary_negotiator",
        "career_planner",
    }
    assert all(c["input_tokens"] == 10 for c in result["consult_calls"])
    assert all("tool_call_details" in c for c in result["consult_calls"])


def test_limits_enforced() -> None:
    always_more = '{"next_agents": ["salary_negotiator", "career_planner", "job_matcher", "resume_advisor", "interviewer"], "tasks": {}, "final_answer": ""}'
    finish = '{"next_agents": [], "tasks": {}, "final_answer": "已达上限，综合如下"}'
    llm = FakeDecisionLLM([always_more, always_more, always_more, finish])
    result = _run(llm, max_rounds=3, max_group_size=3, max_total_calls=8)
    assert len(result["consult_calls"]) == 8
    assert result["synthesis"] == "已达上限，综合如下"


def test_invalid_agents_filtered() -> None:
    llm = FakeDecisionLLM([
        '{"next_agents": ["unknown_agent", "career_planner", "salary_negotiator"], "tasks": {}, "final_answer": ""}',
        '{"next_agents": [], "tasks": {}, "final_answer": "过滤后结论"}',
    ])
    result = _run(llm)
    assert {c["agent"] for c in result["consult_calls"]} == {
        "career_planner",
        "salary_negotiator",
    }


def test_parse_failure_falls_back_to_planner() -> None:
    llm = FakeDecisionLLM(["not-json", "still-not-json", "still-not-json"])
    result = _run(llm)
    assert len(result["consult_calls"]) == 1
    assert result["consult_calls"][0]["agent"] == "career_planner"
    assert result["synthesis"] == ""


def test_needs_user_input_propagated() -> None:
    """信息不足时，决策的 needs_user_input / input_fields 透传到结果。"""
    llm = FakeDecisionLLM([
        '{"next_agents": [], "tasks": {}, "final_answer": "请先补充你的基本信息", '
        '"needs_user_input": true, "input_fields": ["current_position", "experience_years", "skills", "target_direction"]}',
    ])
    result = _run(llm)
    assert result["needs_user_input"] is True
    assert set(result["input_fields"]) == {
        "current_position", "experience_years", "skills", "target_direction",
    }
    assert result["synthesis"] == "请先补充你的基本信息"
    assert result["consult_calls"] == []


def test_needs_user_input_default_false() -> None:
    """不声明 needs_user_input 时保持默认 False（旧决策格式兼容）。

    首轮直接结束且未请求用户输入 -> 触发兜底调度一次最相关顾问。
    """
    llm = FakeDecisionLLM([
        '{"next_agents": [], "tasks": {}, "final_answer": "综合结论"}',
        '{"next_agents": [], "tasks": {}, "final_answer": "综合结论"}',
    ])
    result = _run(llm)
    assert result.get("needs_user_input") is False
    assert result.get("input_fields") == []
    # 默认问题"这个 offer 要不要接" -> 兜底调度薪资谈判师
    assert len(result["consult_calls"]) == 1
    assert result["consult_calls"][0]["agent"] == "salary_negotiator"


def test_input_fields_filtered_to_known() -> None:
    """未知字段被过滤，且不超过预定义字段数量。"""
    llm = FakeDecisionLLM([
        '{"next_agents": [], "tasks": {}, "final_answer": "请补充", '
        '"needs_user_input": true, "input_fields": ["current_position", "hacker_skill", "target_companies"]}',
    ])
    result = _run(llm)
    assert result["needs_user_input"] is True
    assert result["input_fields"] == ["current_position", "target_companies"]


def test_first_round_never_ends_without_agent() -> None:
    """会诊兜底：信息足够但 LLM 首轮就想直接结束时，强制调度一位最相关顾问。"""
    llm = FakeDecisionLLM([
        '{"next_agents": [], "tasks": {}, "final_answer": "直接建议"}',
        '{"next_agents": [], "tasks": {}, "final_answer": "综合顾问意见后的结论"}',
    ])
    result = _run(llm)
    assert len(result["consult_calls"]) == 1
    # 默认问题含 "offer" -> 路由到薪资谈判师
    assert result["consult_calls"][0]["agent"] == "salary_negotiator"
    assert result["synthesis"] == "综合顾问意见后的结论"


def test_unsafe_request_can_end_without_dispatch() -> None:
    """注入/越界输入由调度官直接拒绝，不把攻击文本继续下发给任一顾问。"""
    llm = FakeDecisionLLM([
        '{"next_agents": [], "tasks": {}, "final_answer": "无法提供内部配置", '
        '"direct_response_reason": "unsupported_or_unsafe"}',
    ])
    result = _run(llm)
    assert result["consult_calls"] == []
    assert result["synthesis"] == "无法提供内部配置"


def test_default_agent_routed_by_keyword() -> None:
    """按问题关键词路由兜底顾问：跳槽/规划 -> career_planner。"""
    llm = FakeDecisionLLM([
        '{"next_agents": [], "tasks": {}, "final_answer": "直接建议"}',
        '{"next_agents": [], "tasks": {}, "final_answer": "结论"}',
    ])
    app = build_consult_orchestrator_graph(
        llm,
        lambda n, cb: FakeAgent(n, f"{n} 的意见"),
        max_rounds=3, max_group_size=3, max_total_calls=8,
    )
    result = app.invoke(_state(question="我想跳槽，帮我做职业规划"))
    assert result["consult_calls"][0]["agent"] == "career_planner"
    assert result["synthesis"] == "结论"
