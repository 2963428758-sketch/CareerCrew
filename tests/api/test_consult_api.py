"""Phase 5: consult API 测试（总调度官自动编排）。"""
from __future__ import annotations

import json

import pytest


def _events(resp):
    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    return [json.loads(l) for l in lines]


@pytest.mark.web
def test_consult_stream(client, fake_runtime):
    """自动编排会诊：stage:consult -> dispatch -> agent 事件 -> stage:synthesis -> done。"""
    resp = client.post("/api/consult", json={
        "question": "30K 字节跳动 offer 要不要接？",
    })
    assert resp.status_code == 200
    events = _events(resp)

    assert events[0] == {"type": "stage", "stage": "consult"}

    dispatches = [e for e in events if e["type"] == "dispatch"]
    assert len(dispatches) == 1
    assert dispatches[0]["round"] == 1
    assert set(dispatches[0]["agents"]) == {"salary_negotiator", "career_planner"}

    agent_starts = [e for e in events if e["type"] == "agent_start"]
    agent_ends = [e for e in events if e["type"] == "agent_end"]
    assert len(agent_starts) == 2
    assert len(agent_ends) == 2

    chunks = [e for e in events if e["type"] == "chunk"]
    assert all("agent" in c or e_is_synthesis(c, events) for c in chunks)

    synth_stage = [e for e in events if e["type"] == "stage" and e["stage"] == "synthesis"]
    assert len(synth_stage) == 1

    done = events[-1]
    assert done["type"] == "done"
    assert "opinions" in done
    assert "calls" in done
    assert len(done["calls"]) == 2
    assert "salary_negotiator" in done["opinions"]
    assert "career_planner" in done["opinions"]


def e_is_synthesis(chunk, all_events):
    """synthesis chunk 没有 agent 字段（在 stage=synthesis 之后）。"""
    return "agent" not in chunk


@pytest.mark.web
def test_consult_legacy_agents_ignored(client):
    """前端不再传 agents；即使遗留传入也按总调度官自动决策执行。"""
    resp = client.post("/api/consult", json={
        "question": "测试",
        "agents": ["interviewer"],
    })
    assert resp.status_code == 200
    events = _events(resp)
    dispatches = [e for e in events if e["type"] == "dispatch"]
    assert dispatches[0]["agents"] == ["salary_negotiator", "career_planner"]
    done = events[-1]
    assert "salary_negotiator" in done["opinions"]


@pytest.mark.web
def test_consult_single_agent(client, fake_runtime):
    """单顾问自动编排。"""
    def invoke_impl(prompt, config=None):
        fake_runtime._orchestrator_calls += 1
        if fake_runtime._orchestrator_calls == 1:
            return type("R", (), {
                "content": '{"next_agents": ["career_planner"], "tasks": {}, "final_answer": ""}'
            })()
        return type("R", (), {
            "content": '{"next_agents": [], "tasks": {}, "final_answer": "规划建议"}'
        })()

    fake_runtime.orchestrator_override = invoke_impl
    resp = client.post("/api/consult", json={"question": "测试"})
    assert resp.status_code == 200
    events = _events(resp)
    agent_starts = [e for e in events if e["type"] == "agent_start"]
    assert len(agent_starts) == 1
    assert agent_starts[0]["agent"] == "career_planner"


@pytest.mark.web
def test_consult_memory_restores_calls(client, fake_runtime):
    """会诊完成后，/api/memory 可恢复调度过程 calls。"""
    resp = client.post("/api/consult", json={"question": "测试会诊"})
    assert resp.status_code == 200
    done = _events(resp)[-1]

    mem = client.get("/api/memory", params={"thread_id": "consult"}).json()
    events = [m for m in mem if m.get("type") == "agent_response"]
    assert events
    assert events[-1].get("consult_calls")
    assert len(events[-1]["consult_calls"]) == len(done["calls"])


@pytest.mark.web
def test_consult_input_request_event(client, fake_runtime):
    """总调度官判断信息不足时，事件流包含 input_request（前端据此弹填写框）。"""
    def invoke_impl(prompt, config=None):
        fake_runtime._orchestrator_calls += 1
        return type("R", (), {
            "content": (
                '{"next_agents": [], "tasks": {}, '
                '"final_answer": "请先补充你的基本信息，我再为你做针对性规划", '
                '"needs_user_input": true, '
                '"input_fields": ["current_position", "experience_years", "skills", '
                '"target_direction", "city", "salary", "target_companies"]}'
            )
        })()

    fake_runtime.orchestrator_override = invoke_impl
    resp = client.post("/api/consult", json={"question": "我想跳槽"})
    assert resp.status_code == 200
    events = _events(resp)

    input_reqs = [e for e in events if e["type"] == "input_request"]
    assert len(input_reqs) == 1
    ir = input_reqs[0]
    assert ir["message"]
    ids = [f["id"] for f in ir["fields"]]
    assert set(ids) == {
        "current_position", "experience_years", "skills",
        "target_direction", "city", "salary", "target_companies",
    }
    assert all(f.get("label") for f in ir["fields"])

    # input_request 在 done 之前推送，且最终正常结束
    assert events.index(input_reqs[0]) < events.index(events[-1])
    assert events[-1]["type"] == "done"


@pytest.mark.web
def test_consult_with_profile(client, fake_runtime):
    """资料填写框提交 profile 后正常完成会诊（画像并入上下文，不破坏流程）。"""
    resp = client.post("/api/consult", json={
        "question": "我补充一下我的求职信息：当前职位 / 行业：后端开发 / 互联网；工作年限：3 年",
        "profile": {
            "current_position": "后端开发 / 互联网",
            "experience_years": "3 年",
            "skills": "Python、RAG",
            "target_direction": "大模型工程师",
            "city": "上海",
            "salary": "期望 30-35k",
            "target_companies": "字节、阿里",
        },
    })
    assert resp.status_code == 200
    events = _events(resp)
    assert events[-1]["type"] == "done"
    # 未声明 needs_user_input 时不应下发填写框
    assert all(e["type"] != "input_request" for e in events)


@pytest.mark.web
def test_consult_skips_known_profile_fields(client, fake_runtime):
    """能力画像已有字段不再重复询问：input_request 只下发缺失字段，且画像注入决策上下文。"""
    # 先写入能力画像（技能/方向/经验/城市已有）
    r = client.put("/api/profile?user_id=u_001", json={"fields": {
        "profile.skills": ["Python", "Java"],
        "profile.direction": "后端开发",
        "profile.experience_years": 3,
        "preferences.city": ["广州"],
    }})
    assert r.status_code == 200

    seen_prompts: list[str] = []

    def invoke_impl(prompt, config=None):
        fake_runtime._orchestrator_calls += 1
        seen_prompts.append(prompt)
        # 画像摘要已注入决策 prompt
        assert "Python" in prompt and "后端开发" in prompt
        return type("R", (), {
            "content": (
                '{"next_agents": [], "tasks": {}, '
                '"final_answer": "请先补充缺失信息", '
                '"needs_user_input": true, '
                '"input_fields": ["current_position", "experience_years", "skills", '
                '"target_direction", "city", "salary", "target_companies"]}'
            )
        })()

    fake_runtime.orchestrator_override = invoke_impl
    resp = client.post("/api/consult", json={"question": "我想跳槽"})
    assert resp.status_code == 200
    events = _events(resp)

    input_reqs = [e for e in events if e["type"] == "input_request"]
    assert len(input_reqs) == 1
    ids = [f["id"] for f in input_reqs[0]["fields"]]
    # 画像已有的 skills / experience_years / target_direction / city 不再询问
    assert set(ids) == {"current_position", "salary", "target_companies"}
    assert seen_prompts


@pytest.mark.web
def test_consult_tools_outside_allowlist_clipped(client, fake_runtime):
    """Important 2：consult 请求 tools 含 server 不允许的 id → effective_tools 不含它。"""
    resp = client.post("/api/consult", json={
        "question": "30K 字节跳动 offer 要不要接？",
        "tools": ["rag_query", "evil_tool", "salary_query"],
    })
    assert resp.status_code == 200
    events = _events(resp)
    assert events[-1]["type"] == "done"
    run_id = events[-1]["run_id"]
    run = fake_runtime.conversation_store._db.get_run("u_001", run_id)
    eff = run.get("effective_tools")
    assert "evil_tool" not in eff
    assert "rag_query" in eff
    assert "salary_query" in eff


@pytest.mark.web
def test_consult_hitl_tool_records_awaiting_confirmation(client, fake_runtime):
    """Important 2：consult 中 HITL 工具被拦截 → 落 awaiting_confirmation 行（block-and-record）。"""
    resp = client.post("/api/consult", json={"question": "帮我投递字节跳动"})
    assert resp.status_code == 200
    events = _events(resp)
    assert events[-1]["type"] == "done"
    run_id = events[-1]["run_id"]
    store = fake_runtime.conversation_store
    calls = [c for c in store._db._tool_calls.values() if c["run_id"] == run_id]
    awaiting = [c for c in calls if c.get("status") == "awaiting_confirmation"]
    assert awaiting, "应存在 awaiting_confirmation 的工具调用行"
    assert awaiting[0]["tool_name"] in ("submit_application", "accept_offer")
    assert awaiting[0].get("hitl_status") == "pending"
    assert awaiting[0].get("requires_hitl") is True
