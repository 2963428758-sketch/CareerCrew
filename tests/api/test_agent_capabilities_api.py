"""T3.5 API 层测试：capabilities 端点 + effective_tools 落库 + HITL 记录。

- GET /api/agent/capabilities?module= 形状（id/name/enabled/requires_hitl）
- 请求带 tools=[不允许的] → run 行 effective_tools 不含它（client 不能突破 server allowlist）
- Fake + PG 的 effective_tools 往返（PG 见 tests/integration/test_conversation_pg.py）
"""
from __future__ import annotations

import json

import pytest


@pytest.mark.web
def test_capabilities_endpoint_shape(client, fake_runtime):
    resp = client.get("/api/agent/capabilities?module=chat")
    assert resp.status_code == 200
    body = resp.json()
    assert body["module"] == "chat"
    assert isinstance(body["tools"], list)
    for t in body["tools"]:
        assert set(t.keys()) == {"id", "name", "enabled", "requires_hitl"}
        assert isinstance(t["id"], str)
        assert isinstance(t["name"], str)
        assert isinstance(t["enabled"], bool)
        assert isinstance(t["requires_hitl"], bool)


@pytest.mark.web
def test_capabilities_module_filters(client, fake_runtime):
    """module=resume 只暴露 resume 声明且已注册的工具（registry ∩ module）。"""
    resp = client.get("/api/agent/capabilities?module=resume")
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()["tools"]]
    assert "profile_update" in ids
    assert "rag_query" in ids
    assert "search_jobs" not in ids  # matcher 专属
    assert "memory_search" not in ids  # resume 未声明


@pytest.mark.web
def test_match_tools_outside_allowlist_clipped_and_recorded(client, fake_runtime):
    """请求 tools 含 server 不允许的 id → effective_tools 不含它、agent_runs 行记录裁剪结果。"""
    resp = client.post("/api/chat/match", json={
        "intent": "找工作",
        "tools": ["rag_query", "evil_tool", "memory_search"],
    })
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    run_id = events[-1]["run_id"]
    run = fake_runtime.conversation_store._db.get_run("u_001", run_id)
    eff = run.get("effective_tools")
    assert "evil_tool" not in eff
    assert "rag_query" in eff
    assert "memory_search" in eff


@pytest.mark.web
def test_plan_tools_none_defaults_full_allowlist(client, fake_runtime):
    """未传 tools → effective_tools = 完整 server allowlist（默认全放行）。"""
    resp = client.post("/api/chat/plan", json={"intent": "规划求职"})
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    run_id = events[-1]["run_id"]
    run = fake_runtime.conversation_store._db.get_run("u_001", run_id)
    eff = run.get("effective_tools")
    assert "rag_query" in eff
    assert "profile_update" in eff  # chat 模块声明范围内
