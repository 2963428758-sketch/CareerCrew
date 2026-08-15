"""B3 supervisor 路由 + 图测试。"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.state.checkpointer import get_checkpointer, tenant_checkpoint_config
from careercrew_core.state.settings import Settings
from careercrew_core.supervisor.graph import build_graph
from careercrew_core.supervisor.router import route

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "golden_routes.json"


def test_route_golden_routes() -> None:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    for case in data["routes"]:
        assert route({"stage": case["stage"]}) == case["expected_agent"], case


def test_route_default_stage_is_intent() -> None:
    # 无 stage 默认 intent -> career_planner
    assert route({}) == "career_planner"


def test_route_unknown_stage_to_end() -> None:
    assert route({"stage": "totally_unknown"}) == "__end__"


def test_build_graph_routes_and_terminates(tmp_path: Path, valid_config_data: dict) -> None:
    """route(intent)->career_planner -> 设 stage=apply -> route(apply)->END。"""
    valid_config_data["supervisor"]["checkpointer"]["path"] = str(tmp_path / "cp.db")
    settings = Settings.model_validate(valid_config_data)
    cp = get_checkpointer(settings)

    def career_planner(state):
        return {"stage": "apply", "messages": [AIMessage(content="planned", name="career_planner")]}

    def job_matcher(state):
        return {"stage": "apply", "messages": [AIMessage(content="matched", name="job_matcher")]}

    app = build_graph({"career_planner": career_planner, "job_matcher": job_matcher}, checkpointer=cp)
    init = {
        "thread_id": "t1", "user_id": "u1", "stage": "intent", "user_intent": "找大模型工作",
        "messages": [HumanMessage(content="开始")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    result = app.invoke(init, config=tenant_checkpoint_config("u1", "t1"))
    assert result["stage"] == "apply"
    contents = [getattr(m, "content", "") for m in result["messages"]]
    assert "planned" in contents


def test_build_graph_compiles_without_checkpointer() -> None:
    app = build_graph({"career_planner": lambda s: {"stage": "apply"}}, checkpointer=None)
    assert app is not None
