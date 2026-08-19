"""T2.3 API 测试：会话菜单端点（rename/delete/clear/export）+ 跨用户 404。

依赖 tenant_api fixture（真实认证 alice/bob + FakeRuntime + FakeConversationDb）：
- 通过 POST /api/threads 建 conversation（带 legacy thread_id 登记 memory 元数据）；
- 通过流式端点（match/plan/knowledge）落真实 message/run/sources；
- PATCH rename / POST clear / GET export / DELETE delete 真生生效；
- 跨用户一律 404；export 不含敏感字段。
"""
from __future__ import annotations

import json

import pytest


def _make_thread(client, headers, thread_id: str, module: str = "chat", title: str = "T"):
    resp = client.post(
        "/api/threads",
        json={"thread_id": thread_id, "module": module, "title": title},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _plan_turn(client, headers, thread_id: str) -> dict:
    """通过 chat plan 流式端点落 user+assistant message + run，返回 done 事件。"""
    resp = client.post(
        "/api/chat/plan", json={"intent": "大模型求职", "thread_id": thread_id}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    events = [json.loads(l) for l in resp.text.splitlines() if l.strip()]
    done = [e for e in events if e.get("type") == "done"][-1]
    return done


@pytest.mark.web
def test_menu_crud_and_export(tenant_api):
    client, runtime, headers, _ids = tenant_api
    alice = headers["alice"]

    # create conversation (legacy thread_id) + plan turn 落 message/run
    created = _make_thread(client, alice, "t-menu-1", module="chat", title="求职咨询")
    thread_uuid = created["thread_id"]
    done = _plan_turn(client, alice, "t-menu-1")
    assert done.get("message_id")

    # ── rename ──
    r = client.patch(
        "/api/threads/t-menu-1", json={"title": "改名后"}, headers=alice
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "改名后"
    assert runtime.conversation_store.get_conversation("t-menu-1", _ids["alice"])["title"] == "改名后"

    # ── export md ──
    md = client.get("/api/threads/t-menu-1/export", params={"format": "md"}, headers=alice)
    assert md.status_code == 200, md.text
    md_text = md.text
    assert "# " in md_text                       # Title 标题
    assert "## User" in md_text or "## 用户" in md_text
    assert "## Assistant" in md_text or "## 助手" in md_text

    # ── export json ──
    js = client.get("/api/threads/t-menu-1/export", params={"format": "json"}, headers=alice)
    assert js.status_code == 200, js.text
    body = js.json()
    assert "thread" in body
    assert "messages" in body
    assert "runs" in body
    assert any(run.get("model") for run in body["runs"])
    # 敏感字段不得出现（title/正文可含，但绝无 token/system_prompt/secret）
    exported = json.dumps(body, ensure_ascii=False)
    for secret in ("api_key", "system_prompt", "token", "sk-", "lsv2_"):
        assert secret not in exported, f"泄露敏感字段: {secret}"

    # ── clear ──
    c = client.post("/api/threads/t-menu-1/clear", headers=alice)
    assert c.status_code == 200, c.text
    assert runtime.conversation_store.list_messages("t-menu-1", _ids["alice"]) == []
    conv = runtime.conversation_store.get_conversation("t-menu-1", _ids["alice"])
    assert conv is not None and conv["title"] == "改名后"
    # 清空同时清除 legacy episodic 情景事件（防止 restoreHistory 回退记忆复活旧消息）
    assert runtime.memory_db.list_episodic(_ids["alice"], thread_id="t-menu-1") == []

    # ── delete ──
    d = client.delete("/api/threads/t-menu-1", headers=alice)
    assert d.status_code == 200, d.text
    assert runtime.conversation_store.get_conversation("t-menu-1", _ids["alice"]) is None

    # 删除后再 rename/clear/export 均 404
    assert client.patch("/api/threads/t-menu-1", json={"title": "x"}, headers=alice).status_code == 404
    assert client.post("/api/threads/t-menu-1/clear", headers=alice).status_code == 404
    assert client.get("/api/threads/t-menu-1/export", params={"format": "md"}, headers=alice).status_code == 404


@pytest.mark.web
def test_cross_user_404_for_all_menu_endpoints(tenant_api):
    client, _runtime, headers, ids = tenant_api
    alice, bob = headers["alice"], headers["bob"]

    _make_thread(client, alice, "t-cross", module="chat", title="Alice 私有")
    _plan_turn(client, alice, "t-cross")

    # Bob 访问 alice 的 thread：四类端点全部 404
    assert client.patch("/api/threads/t-cross", json={"title": "偷改"}, headers=bob).status_code == 404
    assert client.post("/api/threads/t-cross/clear", headers=bob).status_code == 404
    assert client.delete("/api/threads/t-cross", headers=bob).status_code == 404
    assert client.get("/api/threads/t-cross/export", params={"format": "md"}, headers=bob).status_code == 404
    assert client.get("/api/threads/t-cross/export", params={"format": "json"}, headers=bob).status_code == 404


@pytest.mark.web
def test_export_missing_conversation_404(tenant_api):
    """无 conversation 行（仅 legacy thread_store 元数据）→ export 404（决策：不 fallback episodic）。"""
    client, runtime, headers, _ids = tenant_api
    alice = headers["alice"]
    # 仅登记 memory 线程元数据，不建 conversation
    runtime.register_thread("t-legacy-only", _ids["alice"], module="chat", title="老线程")
    assert client.get(
        "/api/threads/t-legacy-only/export", params={"format": "md"}, headers=alice
    ).status_code == 404
    assert client.get(
        "/api/threads/t-legacy-only/export", params={"format": "json"}, headers=alice
    ).status_code == 404


@pytest.mark.web
def test_export_invalid_format_400(tenant_api):
    client, _runtime, headers, _ids = tenant_api
    alice = headers["alice"]
    _make_thread(client, alice, "t-fmt", module="chat", title="T")
    assert client.get(
        "/api/threads/t-fmt/export", params={"format": "xml"}, headers=alice
    ).status_code == 400


@pytest.mark.web
def test_clear_empty_conversation_ok(tenant_api):
    client, runtime, headers, ids = tenant_api
    alice = headers["alice"]
    _make_thread(client, alice, "t-clear-empty", module="chat", title="空会话")
    r = client.post("/api/threads/t-clear-empty/clear", headers=alice)
    assert r.status_code == 200
    assert runtime.conversation_store.get_conversation("t-clear-empty", ids["alice"]) is not None


@pytest.mark.web
def test_delete_legacy_only_thread(tenant_api):
    """仅 legacy thread_store 元数据（无 conversation 行）→ DELETE 仍成功（回归修复）。"""
    client, runtime, headers, ids = tenant_api
    alice = headers["alice"]
    # 仅登记 memory 线程元数据，不建 conversation
    runtime.register_thread("t-legacy-del", ids["alice"], module="chat", title="老线程")
    assert runtime.conversation_store.get_conversation("t-legacy-del", ids["alice"]) is None

    d = client.delete("/api/threads/t-legacy-del", headers=alice)
    assert d.status_code == 200, d.text
    # legacy thread_store 元数据已删
    assert runtime.thread_store.get(ids["alice"], "t-legacy-del") is None


@pytest.mark.web
def test_delete_conversation_only_thread(tenant_api):
    """有 conversation 行但无 legacy thread_store 元数据 → DELETE 仍成功。"""
    client, runtime, headers, ids = tenant_api
    alice = headers["alice"]
    # 直接用 store 建 conversation（不经 register_thread，无 legacy 元数据）
    runtime.conversation_store.ensure_conversation("t-conv-only", ids["alice"], "chat", "T")
    assert runtime.thread_store.get(ids["alice"], "t-conv-only") is None

    d = client.delete("/api/threads/t-conv-only", headers=alice)
    assert d.status_code == 200, d.text
    assert runtime.conversation_store.get_conversation("t-conv-only", ids["alice"]) is None


@pytest.mark.web
def test_delete_missing_thread_404(tenant_api):
    """两者都不存在 → DELETE 404。"""
    client, _runtime, headers, _ids = tenant_api
    alice = headers["alice"]
    d = client.delete("/api/threads/t-never-existed", headers=alice)
    assert d.status_code == 404
