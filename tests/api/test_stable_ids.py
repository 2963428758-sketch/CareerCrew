"""T1.2：稳定 ID 接线测试 —— done 事件 §9 字段 + threads 创建 + messages 恢复 + 所有权 + legacy 映射。

用 FakeRuntime（已内置 FakeConversationDb 对话存储 + begin/finish turn 行为）走真实
FastAPI 依赖链，验证：
- 全部流式端点 done 事件携带 §9 字段（thread_id/turn_id/message_id/run_id/model/
  prompt_version/agent_version/status + 可选 legacy_thread_id），UUID 合法。
- POST /api/threads 创建成功、module 非法 422。
- GET /api/threads/{id}/messages 返回 user+assistant 两条、状态 completed、稳定 ID。
- 跨用户 messages 读取 404。
- legacy thread_id 映射稳定（同 legacy 复用同 UUID，done 带 legacy_thread_id）。
- 流异常 → assistant message status=failed。
"""
from __future__ import annotations

import json
import uuid

import pytest

from careercrew_api.sse import StreamCancelled


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


import re


def _last_done(resp) -> dict:
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    done = events[-1]
    assert done["type"] == "done", events
    return done


_SECT_9_KEYS = (
    "thread_id", "turn_id", "message_id", "run_id", "model",
    "prompt_version", "agent_version", "status",
)


def _assert_done_sect9(done: dict) -> None:
    for k in _SECT_9_KEYS:
        assert k in done, f"done 缺 {k}: {done}"
    assert _valid_uuid(done["thread_id"])
    assert _valid_uuid(done["turn_id"])
    assert _valid_uuid(done["message_id"])
    assert _valid_uuid(done["run_id"])
    assert done["status"] == "completed"
    # T1.5：有单一 agent prompt 的入口 prompt_version 为 sha256:<64hex>；
    # consult 编排（无单一 prompt）保持 unversioned。
    assert done["prompt_version"] in ("unversioned",) or re.fullmatch(
        r"sha256:[0-9a-f]{64}", done["prompt_version"]
    )
    # agent_version 为 git sha 或 unversioned，绝不 "unknown"。
    assert done["agent_version"] != "unknown"
    assert done["agent_version"] == "unversioned" or re.fullmatch(
        r"[0-9a-f]{40}", done["agent_version"]
    )


# ── done 事件 §9 字段 ──


@pytest.mark.web
def test_done_prompt_version_is_sha256_for_prompt_agents(client):
    """有单一 agent prompt 的端点，done.prompt_version 为 sha256:<64hex>（非 unversioned）。"""
    import re

    for path, payload in [
        ("/api/chat/match", {"intent": "求职", "thread_id": "vp-1"}),
        ("/api/chat/plan", {"intent": "规划", "thread_id": "vp-2"}),
        ("/api/chat/resume", {"jd_text": "字节", "thread_id": "vp-3"}),
        ("/api/knowledge/ask", {"question": "RAG", "thread_id": "vp-4"}),
        ("/api/interview/questions", {"topic": "RAG", "thread_id": "vp-5"}),
    ]:
        resp = client.post(path, json=payload)
        assert resp.status_code == 200, path
        done = _last_done(resp)
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", done["prompt_version"]), (
            path, done["prompt_version"],
        )


@pytest.mark.web
def test_consult_done_prompt_version_unversioned(client):
    """会诊编排无单一 agent prompt → prompt_version 保持 unversioned（Phase 2/3 再补）。"""
    resp = client.post("/api/consult", json={"question": "谈薪", "thread_id": "c-vp"})
    assert resp.status_code == 200
    done = _last_done(resp)
    assert done["prompt_version"] == "unversioned"
    assert done["agent_version"] != "unknown"


@pytest.mark.web
def test_interview_chat_uses_interviewer_chat_prompt_version(client):
    """面试对话式入口使用 interviewer_chat 独立 prompt，版本与 interviewer.txt 区分。"""
    from careercrew_core.versioning import prompt_version_for_agent

    resp = client.post("/api/interview/chat", json={"topic": "RAG", "messages": []})
    assert resp.status_code == 200
    done = _last_done(resp)
    assert done["prompt_version"] == prompt_version_for_agent("interviewer_chat")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", done["prompt_version"])


@pytest.mark.web
def test_match_done_carries_sect9_fields(client, fake_runtime):
    resp = client.post("/api/chat/match", json={"intent": "大模型方向", "thread_id": "m-legacy"})
    assert resp.status_code == 200
    done = _last_done(resp)
    _assert_done_sect9(done)
    assert "legacy_thread_id" in done  # 非 UUID thread_id → legacy 映射发生
    assert done["legacy_thread_id"] == "m-legacy"


@pytest.mark.web
def test_plan_done_carries_sect9_fields(client):
    resp = client.post("/api/chat/plan", json={"intent": "规划", "thread_id": "p-1"})
    assert resp.status_code == 200
    _assert_done_sect9(_last_done(resp))


@pytest.mark.web
def test_resume_done_carries_sect9_fields(client):
    resp = client.post("/api/chat/resume", json={"jd_text": "字节", "thread_id": "r-1"})
    assert resp.status_code == 200
    _assert_done_sect9(_last_done(resp))


@pytest.mark.web
def test_knowledge_done_carries_sect9_fields(client):
    resp = client.post("/api/knowledge/ask", json={"question": "RAG", "thread_id": "k-1"})
    assert resp.status_code == 200
    done = _last_done(resp)
    _assert_done_sect9(done)
    assert "sources" in done


@pytest.mark.web
def test_interview_questions_done_carries_sect9_fields(client):
    resp = client.post("/api/interview/questions", json={"topic": "RAG", "thread_id": "i-1"})
    assert resp.status_code == 200
    _assert_done_sect9(_last_done(resp))


@pytest.mark.web
def test_consult_done_carries_sect9_fields(client):
    resp = client.post("/api/consult", json={"question": "谈薪", "thread_id": "c-1"})
    assert resp.status_code == 200
    _assert_done_sect9(_last_done(resp))


@pytest.mark.web
def test_same_request_turn_stable_message_run_unique(client, fake_runtime):
    """同一请求内 turn_id 稳定、message_id 与 run_id 唯一且互异。"""
    resp = client.post("/api/chat/match", json={"intent": "求职", "thread_id": "stable-1"})
    done = _last_done(resp)
    assert done["message_id"] != done["run_id"]
    assert done["turn_id"] != done["message_id"]


# ── threads API ──


@pytest.mark.web
def test_create_thread_server_uuid(client):
    resp = client.post("/api/threads", json={"module": "chat", "title": "新会话"})
    assert resp.status_code == 200
    data = resp.json()
    assert _valid_uuid(data["thread_id"])
    assert data["module"] == "chat"
    assert data["title"] == "新会话"
    assert "created_at" in data


@pytest.mark.web
def test_create_thread_invalid_module_422(client):
    assert client.post("/api/threads", json={"module": "bogus"}).status_code == 422


@pytest.mark.web
def test_messages_roundtrip_user_and_assistant(client):
    """match 流结束 → messages 含 user+assistant 两条、status completed、稳定 ID。"""
    resp = client.post("/api/chat/match", json={"intent": "求职", "thread_id": "mt-1"})
    done = _last_done(resp)
    thread_id = done["thread_id"]

    msgs = client.get(f"/api/threads/{thread_id}/messages").json()
    assert len(msgs) == 2
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant"]
    user_msg, asst_msg = msgs
    assert user_msg["status"] == "completed"
    assert asst_msg["status"] == "completed"
    assert asst_msg["id"] == done["message_id"]
    assert asst_msg["run_id"] == done["run_id"]
    assert user_msg["id"] != asst_msg["id"]


@pytest.mark.web
def test_knowledge_messages_include_metadata_sources(client):
    """knowledge 流结束 → assistant message 的 metadata 含 sources。"""
    resp = client.post("/api/knowledge/ask", json={"question": "RAG", "thread_id": "k-meta"})
    done = _last_done(resp)
    msgs = client.get(f"/api/threads/{done['thread_id']}/messages").json()
    asst = [m for m in msgs if m["role"] == "assistant"][0]
    assert asst["metadata"] is not None
    assert "sources" in asst["metadata"]
    assert asst["metadata"]["sources"] == done.get("sources", [])


@pytest.mark.web
def test_consult_messages_include_metadata_opinions(client):
    """consult 流结束 → assistant message 的 metadata 含 opinions。"""
    resp = client.post("/api/consult", json={"question": "谈薪", "thread_id": "c-meta"})
    done = _last_done(resp)
    msgs = client.get(f"/api/threads/{done['thread_id']}/messages").json()
    asst = [m for m in msgs if m["role"] == "assistant"][0]
    assert asst["metadata"] is not None
    assert "opinions" in asst["metadata"]
    assert asst["metadata"]["opinions"] == done.get("opinions", {})


@pytest.mark.web
def test_messages_cross_user_404(tenant_api):
    """User B GET User A 的 messages → 404。"""
    client, _rt, headers, _ids = tenant_api
    resp = client.post("/api/chat/match", json={"intent": "求职", "thread_id": "iso-1"},
                       headers=headers["alice"])
    done = _last_done(resp)
    got = client.get(f"/api/threads/{done['thread_id']}/messages", headers=headers["bob"])
    assert got.status_code == 404


@pytest.mark.web
def test_legacy_thread_mapping_stable(client):
    """legacy thread_id 两次请求映射稳定，done 带 legacy_thread_id。"""
    resp1 = client.post("/api/chat/match", json={"intent": "a", "thread_id": "legacy-x"})
    resp2 = client.post("/api/chat/match", json={"intent": "b", "thread_id": "legacy-x"})
    done1 = _last_done(resp1)
    done2 = _last_done(resp2)
    assert done1["legacy_thread_id"] == "legacy-x"
    assert done2["legacy_thread_id"] == "legacy-x"
    assert done1["thread_id"] == done2["thread_id"]  # 同 legacy → 同 UUID
    assert done1["message_id"] != done2["message_id"]


# ── 失败 / 取消状态 ──


@pytest.mark.web
def test_stream_error_marks_assistant_failed(client, fake_runtime):
    """run 抛异常 → assistant message status=failed。"""
    original = fake_runtime.run_match_stream

    def boom(thread_id, user_id, intent, cb=None, cancel_check=None):
        from careercrew_api.chat_lifecycle import StreamResult

        ctx = fake_runtime._begin_chat_turn(
            thread_id, user_id, module="matcher", agent_id="job_matcher", user_text=intent,
        )
        fake_runtime._fail_chat_turn(ctx, RuntimeError("测试异常"))
        raise RuntimeError("测试异常")

    fake_runtime.run_match_stream = boom
    try:
        resp = client.post("/api/chat/match", json={"intent": "测试", "thread_id": "err-1"})
        assert any(json.loads(l)["type"] == "error" for l in resp.text.strip().split("\n"))
    finally:
        fake_runtime.run_match_stream = original

    # 通过 runtime 的对话存储直接断言消息状态
    conv = fake_runtime.conversation_store.get_conversation("err-1", "u_001")
    msgs = fake_runtime.conversation_store.list_messages("err-1", "u_001")
    asst = [m for m in msgs if m["role"] == "assistant"][0]
    assert asst["status"] == "failed"
