"""Phase 5: consult API 测试（FakeAgent 并行）。"""
from __future__ import annotations

import json

import pytest


@pytest.mark.web
def test_consult_stream(client, fake_runtime):
    """并行会诊：stage:consult -> agent_start/chunk/agent_end -> stage:synthesis -> done。"""
    resp = client.post("/api/consult", json={
        "question": "30K 字节跳动 offer 要不要接？",
        "agents": ["salary_negotiator", "career_planner"],
    })
    assert resp.status_code == 200
    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    events = [json.loads(l) for l in lines]

    # 第一个事件是 stage=consult
    assert events[0] == {"type": "stage", "stage": "consult"}

    # 有 agent_start / chunk / agent_end
    agent_starts = [e for e in events if e["type"] == "agent_start"]
    agent_ends = [e for e in events if e["type"] == "agent_end"]
    assert len(agent_starts) == 2
    assert len(agent_ends) == 2

    # chunks 带 agent 字段
    chunks = [e for e in events if e["type"] == "chunk"]
    assert all("agent" in c or e_is_synthesis(c, events) for c in chunks)

    # 有 stage=synthesis
    synth_stage = [e for e in events if e["type"] == "stage" and e["stage"] == "synthesis"]
    assert len(synth_stage) == 1

    # 最后是 done，带 opinions
    done = events[-1]
    assert done["type"] == "done"
    assert "opinions" in done
    assert "salary_negotiator" in done["opinions"]
    assert "career_planner" in done["opinions"]


def e_is_synthesis(chunk, all_events):
    """synthesis chunk 没有 agent 字段（在 stage=synthesis 之后）。"""
    return "agent" not in chunk


@pytest.mark.web
def test_consult_default_agents(client):
    """默认 agents=salary_negotiator+career_planner。"""
    resp = client.post("/api/consult", json={"question": "测试"})
    assert resp.status_code == 200
    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    events = [json.loads(l) for l in lines]
    done = events[-1]
    assert "salary_negotiator" in done["opinions"]


@pytest.mark.web
def test_consult_single_agent(client, fake_runtime):
    """单 agent 会诊。"""
    resp = client.post("/api/consult", json={
        "question": "测试",
        "agents": ["salary_negotiator"],
    })
    assert resp.status_code == 200
    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    events = [json.loads(l) for l in lines]
    agent_starts = [e for e in events if e["type"] == "agent_start"]
    assert len(agent_starts) == 1


@pytest.mark.web
def test_consult_all_five_agents(client):
    """会诊放开全部 5 个业务 agent：job_matcher / resume_advisor / interviewer 可勾选。"""
    resp = client.post("/api/consult", json={
        "question": "30K 字节跳动 offer 要不要接？",
        "agents": ["job_matcher", "resume_advisor", "interviewer", "salary_negotiator", "career_planner"],
    })
    assert resp.status_code == 200
    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    events = [json.loads(l) for l in lines]

    agent_starts = [e for e in events if e["type"] == "agent_start"]
    agent_ends = [e for e in events if e["type"] == "agent_end"]
    assert len(agent_starts) == 5
    assert len(agent_ends) == 5

    done = events[-1]
    assert done["type"] == "done"
    for name in ("job_matcher", "resume_advisor", "interviewer", "salary_negotiator", "career_planner"):
        assert name in done["opinions"]
