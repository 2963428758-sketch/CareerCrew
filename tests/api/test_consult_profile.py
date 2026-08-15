"""会诊 current_position 画像字段：投影、持久化与显式清空。"""
from __future__ import annotations

from careercrew_core.memory.types import UserProfile


def test_profile_from_model_includes_current_position():
    from careercrew_api.routers.consult import _profile_from_model

    model = type("M", (), {
        "profile": UserProfile(current_position="后端开发 / 互联网"),
        "preferences": type("P", (), {"city": [], "salary_min": None, "salary_max": None})(),
        "target_companies": [],
    })()
    assert _profile_from_model(model)["current_position"] == "后端开发 / 互联网"


def test_update_profile_clears_current_position(client):
    client.put("/api/profile", json={"fields": {"profile.current_position": "后端"}})
    assert client.get("/api/profile").json()["profile"]["current_position"] == "后端"
    client.put("/api/profile", json={"fields": {"profile.current_position": ""}})
    assert client.get("/api/profile").json()["profile"]["current_position"] == ""


def test_consult_form_persists_current_position(client, fake_runtime):
    """会诊带 profile 提交时 current_position 落画像，后续 /api/profile 可读。"""
    fake_runtime.orchestrator_override = lambda prompt, config=None: type("R", (), {
        "content": '{"next_agents": [], "tasks": {}, "final_answer": "ok", '
                   '"needs_user_input": false, "input_fields": []}'})()
    with client.stream("POST", "/api/consult", json={
        "question": "帮我规划",
        "thread_id": "c-pos",
        "profile": {"current_position": "后端开发 / 互联网"},
    }) as resp:
        lines = [l for l in resp.iter_lines() if l.strip()]
    assert any('"type": "done"' in l for l in lines)
    assert client.get("/api/profile").json()["profile"]["current_position"] == "后端开发 / 互联网"
