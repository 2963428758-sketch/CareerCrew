"""E3/E4 职位匹配官测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.agents.job_matcher import JobMatcher, score_jd_match
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.tools.internal.memory_write import make_memory_write_tool
from careercrew_core.tools.internal.search_jobs import search_jobs
from careercrew_core.tools.registry import ToolRegistry, ToolSpec


def test_score_jd_match_perfect() -> None:
    profile = {"skills": ["Python", "LangChain", "RAG"], "direction": "大模型应用"}
    jd = "需要 Python、LangChain、RAG 经验，方向大模型应用"
    assert score_jd_match(jd, profile) == 1.0


def test_score_jd_match_partial() -> None:
    profile = {"skills": ["Python", "Java"], "direction": "大模型应用"}
    jd = "Java 后端开发，不涉及大模型"  # 注意"大模型应用"不是子串
    # Java 命中, Python 未命中, 方向未命中 -> 1/3
    assert score_jd_match(jd, profile) == round(1 / 3, 3)


def test_score_jd_match_empty() -> None:
    assert score_jd_match("", {"skills": ["Python"]}) == 0.0
    assert score_jd_match("Java", {}) == 0.0


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


def test_job_matcher_accepts_tracer(tmp_path) -> None:
    """回归：所有 agent 子类必须透传 tracer（CLI chat 传 tracer 会失败）。"""
    from careercrew_core.tracing.trace import TraceRecorder

    llm = FakeChatModel([AIMessage(content="匹配结果")])
    agent = JobMatcher(llm=llm, tools=ToolRegistry(), tracer=TraceRecorder(tmp_path / "t.jsonl"))
    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "match", "user_intent": "找岗位",
        "messages": [HumanMessage(content="找岗位")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)
    assert agent.last_result.content == "匹配结果"


def test_job_matcher_writes_job_match(tmp_path) -> None:
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("search_jobs", {"direction": "大模型应用", "top_k": 3}, "c1")]),
        AIMessage(content="", tool_calls=[_tc("memory_write", {"type": "job_match", "content": {"company": "字节", "title": "大模型工程师", "score": 0.9}}, "c2")]),
        AIMessage(content="匹配到字节跳动"),
    ])
    episodic = EpisodicMemory(tmp_path / "t.jsonl")
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=search_jobs))
    reg.register(ToolSpec(tool=make_memory_write_tool(episodic)))
    agent = JobMatcher(llm=llm, tools=reg, max_iterations=5)
    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "match", "user_intent": "找大模型岗位",
        "messages": [HumanMessage(content="找大模型岗位")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)
    assert agent.last_result.content == "匹配到字节跳动"
    # job_match 已写入 episodic
    entries = episodic._read_all()
    assert any(e.type == "job_match" and e.content["company"] == "字节" for e in entries)
