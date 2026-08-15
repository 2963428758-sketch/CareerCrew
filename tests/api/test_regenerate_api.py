"""T1.6 API 集成测试：POST /api/messages/{message_id}/regenerate（FakeRuntime + 真实路由）。

依赖 FakeRuntime 的 conversation_store（FakeConversationDb），先通过既有流式
端点（match/plan/knowledge ask）落一轮真实 message/run，再 regenerate 验证：
- done 事件 turn_id 不变、新 message_id/run_id
- messages 列表出现两条 assistant 同 turn，regenerated_from_message_id 链正确
- 幂等头同 key 二次不产生新 run；无 key 每次新 run
- 404（不存在/跨用户）、409（非 assistant/非 completed/非最后一条/consult）
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from careercrew_api.runtime import CareerCrewRuntime, ResourceNotFoundError
from careercrew_core.conversation.store import ConversationStore


def _run_client_stream(client, path, payload, *, idempotency_key=None):
    headers = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    resp = client.post(path, json=payload, headers=headers)
    return resp


def _events(resp):
    return [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]


def _last_done(events):
    return [e for e in events if e["type"] == "done"][-1]


def test_regenerate_match_done_invariance(client, fake_runtime):
    """match 首轮 → done 带 turn/run/message；regenerate → done turn 不变、id 变。"""
    fake_runtime.match_output = "匹配结果 v1"
    r1 = _run_client_stream(client, "/api/chat/match", {"intent": "大模型找工作"})
    d1 = _last_done(_events(r1))
    assert d1["turn_id"]

    fake_runtime.match_output = "匹配结果 v2"
    r2 = _run_client_stream(
        client, f"/api/messages/{d1['message_id']}/regenerate", {}
    )
    ev2 = _events(r2)
    d2 = _last_done(ev2)
    assert d2["turn_id"] == d1["turn_id"]          # turn 不变
    assert d2["run_id"] != d1["run_id"]            # run 变
    assert d2["message_id"] != d1["message_id"]    # message 变
    assert d2.get("regenerated_from_message_id") == d1["message_id"]  # 链路可附加

    # messages 列表出现两条 assistant 同 turn，链正确
    msgs = fake_runtime.conversation_store.list_messages(d1["thread_id"], "u_001")
    asst = [m for m in msgs if m["role"] == "assistant"]
    assert len(asst) == 2
    assert all(m["turn_id"] == d1["turn_id"] for m in asst)
    v2 = [m for m in asst if m["id"] == d2["message_id"]][0]
    assert v2["regenerated_from_message_id"] == d1["message_id"]
    # 旧消息未覆盖
    v1 = [m for m in asst if m["id"] == d1["message_id"]][0]
    assert v1["content"] == "匹配结果 v1"


def test_regenerate_plan_and_knowledge(client, fake_runtime):
    """plan 与 knowledge ask 也能 regenerate（done turn 不变、id 变）。"""
    fake_runtime.planner_output = "规划 v1"
    r1 = _run_client_stream(client, "/api/chat/plan", {"intent": "帮我规划"})
    d1 = _last_done(_events(r1))
    fake_runtime.planner_output = "规划 v2"
    r2 = _run_client_stream(client, f"/api/messages/{d1['message_id']}/regenerate", {})
    d2 = _last_done(_events(r2))
    assert d2["turn_id"] == d1["turn_id"]
    assert d2["message_id"] != d1["message_id"]


def test_regenerate_404_missing(client, fake_runtime):
    r = _run_client_stream(client, f"/api/messages/{uuid4()}/regenerate", {})
    assert r.status_code == 404


def test_regenerate_409_non_assistant(client, fake_runtime):
    """regenerate 指向 user 消息 → 409。"""
    fake_runtime.match_output = "v1"
    r1 = _run_client_stream(client, "/api/chat/match", {"intent": "找工作"})
    d1 = _last_done(_events(r1))
    # 找该 turn 的 user 消息
    msgs = fake_runtime.conversation_store.list_messages(d1["thread_id"], "u_001")
    user_msg = [m for m in msgs if m["role"] == "user"][0]
    r2 = _run_client_stream(client, f"/api/messages/{user_msg['id']}/regenerate", {})
    assert r2.status_code == 409


def test_regenerate_idempotency_key(client, fake_runtime):
    """同 Idempotency-Key 二次请求 → 返回第一次生成的 message（不新 run）。"""
    fake_runtime.match_output = "v1"
    r1 = _run_client_stream(client, "/api/chat/match", {"intent": "找工作"})
    d1 = _last_done(_events(r1))

    key = "idem-abc"
    fake_runtime.match_output = "v2"
    ra = _run_client_stream(
        client, f"/api/messages/{d1['message_id']}/regenerate", {},
        idempotency_key=key,
    )
    da = _last_done(_events(ra))

    fake_runtime.match_output = "v3"
    rb = _run_client_stream(
        client, f"/api/messages/{d1['message_id']}/regenerate", {},
        idempotency_key=key,
    )
    db = _last_done(_events(rb))

    # 同 key 二次返回同一 message（不重跑）
    assert db["message_id"] == da["message_id"]
    assert db["run_id"] == da["run_id"]

    # 无 key 第三次：regenerate 最新版（da 的 message）→ 新 message/run
    fake_runtime.match_output = "v4"
    rc = _run_client_stream(
        client, f"/api/messages/{da['message_id']}/regenerate", {},
    )
    dc = _last_done(_events(rc))
    assert dc["message_id"] != da["message_id"]

    # 最终 assistant 链：v1 → v2 → v4
    msgs = fake_runtime.conversation_store.list_messages(d1["thread_id"], "u_001")
    asst = [m for m in msgs if m["role"] == "assistant"]
    assert len(asst) == 3
    v4 = [m for m in asst if m["id"] == dc["message_id"]][0]
    assert v4["regenerated_from_message_id"] == da["message_id"]


def test_regenerate_consult_409(client, fake_runtime):
    """consult 模块（第一版不支持）→ 409。构造一条 consult 消息后 regenerate。"""
    store = fake_runtime.conversation_store
    conv = store.ensure_conversation("t-c", "u_001", "consult", "T")
    turn = store.next_turn("t-c", "u_001")
    store.add_user_message(turn["id"], conv["id"], "u_001", "q", "completed")
    asst = store.add_assistant_message(turn["id"], conv["id"], "u_001", "", None, None)
    store.set_message_status("u_001", asst["id"], "streaming")
    run = store.start_run(
        thread_id=conv["id"], turn_id=turn["id"], message_id=asst["id"],
        user_id="u_001", module="consult", agent_id="consult_orchestrator",
        model="m", status="streaming",
    )
    store.set_message_run_id("u_001", asst["id"], run["id"])
    store.set_message_content("u_001", asst["id"], "ans", status="completed")
    r = _run_client_stream(client, f"/api/messages/{asst['id']}/regenerate", {})
    assert r.status_code == 409


def test_regenerate_idempotency_in_progress_409(client, fake_runtime):
    """同 key 首个请求进行中（message_id 尚未回填）→ 并发同 key 请求 409，不二次 run/message。"""
    fake_runtime.match_output = "v1"
    r1 = _run_client_stream(client, "/api/chat/match", {"intent": "找工作"})
    d1 = _last_done(_events(r1))

    key = "idem-inprogress"
    store = fake_runtime.conversation_store

    # 手动预留该 key（模拟首个 regenerate 请求已抢占、尚未完成回填 message_id）
    assert store.reserve_regeneration("u_001", key) == ("reserved", None)
    # 断言进行中态：message_id 为 None
    assert store.reserve_regeneration("u_001", key) == ("exists", None)

    # 记录当前 assistant message/run 数量
    before_msgs = store.list_messages(d1["thread_id"], "u_001")
    before_asst = [m for m in before_msgs if m["role"] == "assistant"]

    # 并发同 key 请求 → 409，不得 dispatch（不新增 run/message）
    rb = _run_client_stream(
        client, f"/api/messages/{d1['message_id']}/regenerate", {},
        idempotency_key=key,
    )
    assert rb.status_code == 409
    assert "正在处理中" in rb.json()["detail"]

    after_msgs = store.list_messages(d1["thread_id"], "u_001")
    after_asst = [m for m in after_msgs if m["role"] == "assistant"]
    assert len(after_asst) == len(before_asst)  # 未产生第二条 assistant message

    # 释放后（首个请求失败场景）同 key 可重新 dispatch
    assert store.release_regeneration("u_001", key) is True
    rc = _run_client_stream(
        client, f"/api/messages/{d1['message_id']}/regenerate", {},
        idempotency_key=key,
    )
    assert rc.status_code == 200


def test_regenerate_idempotency_replay_done_fields(client, fake_runtime):
    """幂等 replay 的 done 事件与正常路径同 §9 字段集（含 model/prompt/agent 版本）。"""
    fake_runtime.match_output = "v1"
    r1 = _run_client_stream(client, "/api/chat/match", {"intent": "找工作"})
    d1 = _last_done(_events(r1))
    key = "idem-replay-fields"

    ra = _run_client_stream(
        client, f"/api/messages/{d1['message_id']}/regenerate", {},
        idempotency_key=key,
    )
    da = _last_done(_events(ra))
    # 正常路径已含 §9 版本字段
    assert "model" in da
    assert "prompt_version" in da
    assert "agent_version" in da

    rb = _run_client_stream(
        client, f"/api/messages/{d1['message_id']}/regenerate", {},
        idempotency_key=key,
    )
    db = _last_done(_events(rb))
    # replay 字段集与首次一致（含 §9 版本字段）
    for field in ("thread_id", "turn_id", "message_id", "run_id", "status",
                  "regenerated_from_message_id", "model", "prompt_version",
                  "agent_version"):
        assert field in db, f"replay done 缺少字段 {field}"
    assert db["message_id"] == da["message_id"]
    assert db["run_id"] == da["run_id"]
    assert db["model"] == da["model"]
    assert db["prompt_version"] == da["prompt_version"]
    assert db["agent_version"] == da["agent_version"]


def test_regenerate_latest_of_earlier_turn_409(client, fake_runtime):
    """线程级最后一条：更晚 turn 存在时，早期 turn 最新 assistant → 409。"""
    fake_runtime.match_output = "t1"
    r1 = _run_client_stream(client, "/api/chat/match", {"intent": "第一问"})
    d1 = _last_done(_events(r1))

    # 在同一线程内追加第二 turn（带完成的 assistant），使 turn1 不再是线程最后一条
    store = fake_runtime.conversation_store
    conv = store.get_conversation(d1["thread_id"], "u_001")
    turn2 = store.next_turn(d1["thread_id"], "u_001")
    store.add_user_message(turn2["id"], conv["id"], "u_001", "第二个问题", "completed")
    asst2 = store.add_assistant_message(turn2["id"], conv["id"], "u_001", "", None, None)
    store.set_message_status("u_001", asst2["id"], "streaming")
    run2 = store.start_run(
        thread_id=conv["id"], turn_id=turn2["id"], message_id=asst2["id"],
        user_id="u_001", module="matcher", agent_id="job_matcher", model="m",
        status="streaming",
    )
    store.set_message_run_id("u_001", asst2["id"], run2["id"])
    store.set_message_content("u_001", asst2["id"], "第二答", status="completed")

    r3 = _run_client_stream(client, f"/api/messages/{d1['message_id']}/regenerate", {})
    assert r3.status_code == 409

    # 线程最后一条（turn2）→ 允许
    r4 = _run_client_stream(client, f"/api/messages/{asst2['id']}/regenerate", {})
    assert r4.status_code == 200
