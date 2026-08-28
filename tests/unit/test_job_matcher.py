"""E3/E4 职位匹配官测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.agents.job_matcher import (
    JobMatcher,
    extract_profile_from_intent,
    prompt_source,
    score_jd_match,
)
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.tools.internal.memory_write import make_memory_write_tool
from careercrew_core.tools.internal.search_jobs import search_jobs
from careercrew_core.tools.registry import ToolRegistry, ToolSpec
from tests.fakes import FakeChatModel


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


def _fake_llm(content: str):
    class _FakeLLM:
        def invoke(self, messages, config=None):
            return type("R", (), {"content": content})()
    return _FakeLLM()


def test_extract_profile_from_intent() -> None:
    """从用户最新消息提取明确字段（方向/技能），只信用户亲口说的。"""
    fields = extract_profile_from_intent(
        _fake_llm('{"profile.direction": "大模型应用", "profile.skills": ["Java"]}'),
        "我是大模型应用方向，有 Java 背景",
    )
    assert fields["profile.direction"] == "大模型应用"
    assert fields["profile.skills"] == ["Java"]


def test_extract_profile_from_intent_no_json() -> None:
    """LLM 没输出 JSON → 返回空 dict，不阻塞。"""
    assert extract_profile_from_intent(_fake_llm("抱歉，我无法解析"), "找岗位") == {}
    assert extract_profile_from_intent(None, "找岗位") == {}
    assert extract_profile_from_intent(_fake_llm("{}"), "") == {}


def test_extract_profile_from_intent_type_guard() -> None:
    """类型不符的字段丢弃：skills 应为 list，字符串拒绝（避免写坏 User Model）。"""
    fields = extract_profile_from_intent(
        _fake_llm('{"profile.skills": "Java", "preferences.salary_min": "很多"}'),
        "找岗位",
    )
    assert fields == {}


def _tc(name, args, id_="1"):
    return {"name": name, "args": args, "id": id_, "type": "tool_call"}


def test_job_matcher_writes_job_match() -> None:
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("search_jobs", {"direction": "大模型应用", "top_k": 3}, "c1")]),
        AIMessage(content="", tool_calls=[_tc("memory_write", {"type": "job_match", "content": {"company": "字节", "title": "大模型工程师", "score": 0.9}}, "c2")]),
        AIMessage(content="匹配到字节跳动"),
    ])
    episodic = EpisodicMemory(FakeMemoryDb(), user_id="u1", thread_id="t1")
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


def test_job_matcher_streams_all_chunks() -> None:
    chunks: list[str] = []
    llm = FakeChatModel([
        AIMessage(
            content="让我先搜索一下：",
            tool_calls=[_tc("search_jobs", {"direction": "Java", "top_k": 1}, "c1")],
        ),
        AIMessage(content="## 匹配报告\n| 来源 | 公司 |\n| 猎聘 | 字节 |"),
    ])
    agent = JobMatcher(
        llm=llm,
        tools=[search_jobs],
        max_iterations=3,
        stream_callback=chunks.append,
    )
    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "match", "user_intent": "Java",
        "messages": [HumanMessage(content="Java")], "pending_action": None,
        "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)
    assert "".join(chunks) == "让我先搜索一下：## 匹配报告\n| 来源 | 公司 |\n| 猎聘 | 字节 |"
    assert "## 匹配报告" in agent.last_result.content


def test_job_matcher_recovers_report_attached_to_finalization_tool_call() -> None:
    """报告与 memory_write 同轮、随后模型空结束时，报告被正确生成并流式输出。"""
    chunks: list[str] = []
    report = "## 匹配报告\n| 公司 | 职位 |\n| 麦当劳 | 兼职餐厅服务员 |"
    llm = FakeChatModel([
        AIMessage(
            content="",
            tool_calls=[_tc("search_jobs", {"direction": "餐厅服务员 兼职 深圳"}, "c1")],
        ),
        AIMessage(
            content=report,
            tool_calls=[_tc("memory_write", {
                "type": "job_match",
                "content": {"company": "麦当劳", "title": "兼职餐厅服务员", "score": 0.9},
            }, "c2")],
        ),
        AIMessage(content=""),
    ])
    episodic = EpisodicMemory(FakeMemoryDb(), user_id="u1", thread_id="t1")
    agent = JobMatcher(
        llm=llm,
        tools=[search_jobs, make_memory_write_tool(episodic)],
        max_iterations=4,
        stream_callback=chunks.append,
    )
    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "match",
        "user_intent": "找深圳兼职餐厅服务员",
        "messages": [HumanMessage(content="找深圳兼职餐厅服务员")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)
    assert agent.last_result.content == report
    assert "".join(chunks) == report


def test_job_matcher_prompt_requires_company_and_source_fidelity() -> None:
    prompt = prompt_source()
    assert "source_label" in prompt
    assert "不得把城市、区、商圈或职位名当作公司" in prompt
    assert "不要声称能调用简历顾问" in prompt
    assert "retrieval_mode_label" in prompt
    assert "不要只传“广州”或“教师”" in prompt
    assert "不得把 `retrieval_mode=cache` 描述成" in prompt
    assert "通用服务岗位不强制技能" in prompt
    assert "用户没有相关经验时不得虚构 `profile.skills`" in prompt
    assert "必须传字符串数组" in prompt
    assert "必须再用一条**不含任何工具调用**" in prompt
