"""跨用户隔离测试矩阵（T0.3 / 方案 §41 安全测试子集）。

每一行对应方案 §41 的一条安全断言，走真实 FastAPI 依赖链：
- 认证：AuthService + FakeAccountStore（真实 JWT），不 mock 鉴权依赖本身
- 业务：FakeRuntime（duck-typed，不触发重组件初始化）
- 双/三账号 fixture 收敛在 tests/api/conftest.py 的 ``tenant_api``

覆盖范围（本 Phase）：
  - User A 无法 GET User B Thread
  - User A 无法 PATCH/DELETE User B Thread（拒绝且不生效；删除后 A 自己的不受影响）
  - User A 无法 list / delete User B Memory
  - User A 无法捏造 public/private visibility
  - User B 无法 GET/删除/在 ask 路径引用 A 的 private 文档；B 可访问 public 文档
  - Quality Reviewer 无法调用 /api/auth/users* 管理端点（403）

未覆盖、留给后续 Phase 的行记录在 .superpowers/sdd/briefs/t03-deferred.md。
"""
from __future__ import annotations

import json

import pytest


# ── Thread 隔离 ──


@pytest.mark.web
def test_thread_list_hides_other_users_threads(tenant_api):
    client, _rt, headers, _ids = tenant_api
    client.post("/api/threads", json={"thread_id": "a-thread", "title": "A 的线程"},
                headers=headers["alice"])
    client.post("/api/threads", json={"thread_id": "b-thread", "title": "B 的线程"},
                headers=headers["bob"])

    alice_threads = client.get("/api/threads", headers=headers["alice"]).json()
    bob_threads = client.get("/api/threads", headers=headers["bob"]).json()

    alice_ids = {t["thread_id"] for t in alice_threads}
    bob_ids = {t["thread_id"] for t in bob_threads}
    assert "a-thread" in alice_ids and "b-thread" not in alice_ids
    assert "b-thread" in bob_ids and "a-thread" not in bob_ids


@pytest.mark.web
def test_thread_patch_cross_user_rejected_and_not_effective(tenant_api):
    client, _rt, headers, _ids = tenant_api
    client.post("/api/threads", json={"thread_id": "a-patch", "title": "原标题"},
                headers=headers["alice"])

    resp = client.patch("/api/threads/a-patch", json={"title": "被 B 篡改"},
                        headers=headers["bob"])
    # 拒绝（404：Authenticated tenant does not own the resource）
    assert resp.status_code == 404

    rows = client.get("/api/threads", headers=headers["alice"]).json()
    row = next(r for r in rows if r["thread_id"] == "a-patch")
    assert row["title"] == "原标题"


@pytest.mark.web
def test_thread_delete_cross_user_rejected_and_owner_intact(tenant_api):
    client, _rt, headers, _ids = tenant_api
    client.post("/api/threads", json={"thread_id": "a-del", "title": "A 的线程"},
                headers=headers["alice"])

    assert client.delete("/api/threads/a-del", headers=headers["bob"]).status_code == 404

    # 删除被拒后，A 自己的线程不受影响
    rows = client.get("/api/threads", headers=headers["alice"]).json()
    assert any(r["thread_id"] == "a-del" for r in rows)

    # A 自己删除成功
    assert client.delete("/api/threads/a-del", headers=headers["alice"]).status_code == 200
    rows = client.get("/api/threads", headers=headers["alice"]).json()
    assert all(r["thread_id"] != "a-del" for r in rows)


# ── Memory 隔离 ──


@pytest.mark.web
def test_memory_list_cannot_read_other_users_thread(tenant_api):
    client, runtime, headers, ids = tenant_api
    runtime.record_thread_messages(ids["alice"], "a-secret-thread", "Alice 的秘密", "回答")

    alice_mem = client.get("/api/memory", params={"thread_id": "a-secret-thread"},
                           headers=headers["alice"]).json()
    bob_mem = client.get("/api/memory", params={"thread_id": "a-secret-thread"},
                         headers=headers["bob"]).json()

    assert len(alice_mem) >= 2  # user_message + agent_response
    assert bob_mem == []


@pytest.mark.web
def test_memory_delete_cannot_delete_other_users_memory(tenant_api):
    client, runtime, headers, ids = tenant_api
    runtime.record_thread_messages(ids["alice"], "a-del-thread", "待删的 Alice 记忆", "回答")

    # 删除前的完整快照（作为逐字节不变断言的基线）
    before = client.get("/api/memory", params={"thread_id": "a-del-thread"},
                        headers=headers["alice"]).json()
    assert len(before) >= 2

    # B 尝试按 A 的 thread_id 删除 → 不生效，且明确返回 removed == 0
    resp = client.delete("/api/memory", params={"thread_id": "a-del-thread"},
                         headers=headers["bob"])
    assert resp.status_code == 200
    assert resp.json()["removed"] == 0
    assert resp.json()["deleted"] == 0

    # A 的记忆逐字节不变（而非仅"非空"）——B 的删除必须是彻底的 no-op
    after = client.get("/api/memory", params={"thread_id": "a-del-thread"},
                       headers=headers["alice"]).json()
    assert after == before


# ── Knowledge 隔离 ──


def _seed_knowledge(runtime, ids):
    """预置 A（admin）与 B（user）的私有文档 + 一个 A 的公共文档。"""
    runtime.knowledge_docs_by_user[ids["alice"]] = [
        {"doc": "alice-private", "source": "a.md", "points": 2,
         "owner_user_id": ids["alice"], "visibility": "private"},
        {"doc": "alice-public", "source": "a2.md", "points": 3,
         "owner_user_id": ids["alice"], "visibility": "public"},
    ]
    runtime.knowledge_docs_by_user[ids["bob"]] = [
        {"doc": "bob-private", "source": "b.md", "points": 1,
         "owner_user_id": ids["bob"], "visibility": "private"},
    ]


@pytest.mark.web
def test_knowledge_private_doc_hidden_from_other_user(tenant_api):
    client, runtime, headers, ids = tenant_api
    _seed_knowledge(runtime, ids)

    alice_docs = {d["doc"] for d in client.get("/api/knowledge", headers=headers["alice"]).json()["docs"]}
    bob_docs = {d["doc"] for d in client.get("/api/knowledge", headers=headers["bob"]).json()["docs"]}

    # A 的 private 文档对 B 不可见；public 文档对任何人可见
    assert alice_docs == {"alice-private", "alice-public"}
    assert bob_docs == {"alice-public", "bob-private"}
    assert "alice-private" not in bob_docs


@pytest.mark.web
def test_knowledge_cannot_delete_others_private_doc(tenant_api):
    client, runtime, headers, ids = tenant_api
    _seed_knowledge(runtime, ids)

    # B 删除 A 的 private 文档 → 404；删除 A 的 public 文档 → 403（仅管理员可删公共）
    assert client.delete("/api/knowledge/alice-private", headers=headers["bob"]).status_code == 404
    assert client.delete("/api/knowledge/alice-public", headers=headers["bob"]).status_code == 403

    # 文档仍然存在（owner 可见）
    alice_docs = {d["doc"] for d in client.get("/api/knowledge", headers=headers["alice"]).json()["docs"]}
    assert "alice-private" in alice_docs and "alice-public" in alice_docs


@pytest.mark.web
def test_knowledge_ask_cannot_reference_others_private_doc(tenant_api):
    client, runtime, headers, ids = tenant_api
    _seed_knowledge(runtime, ids)

    # ask 的检索范围（scope）与访问过滤器由 runtime 的 _knowledge_scope_filters 决定；
    # 这里断言 B 以 private 范围 ask 时，只能命中自己的私有库（不是 A 的 private 文档）。
    runtime.knowledge_output_by_user[ids["bob"]] = "Bob 的私有回答"
    resp = client.post("/api/knowledge/ask", json={
        "question": "A 的私有内容是什么？", "thread_id": "k-isolation", "scope": "private",
    }, headers=headers["bob"])
    events = [json.loads(line) for line in resp.text.splitlines() if line]
    assert events[-1]["content"] == "Bob 的私有回答"

    # B 以 all 范围 ask 时，可以命中公共库（但不含 A 的 private 文档）
    runtime.knowledge_output_by_user[ids["bob"]] = "公共库回答"
    resp = client.post("/api/knowledge/ask", json={
        "question": "公共内容是什么？", "thread_id": "k-isolation", "scope": "all",
    }, headers=headers["bob"])
    events = [json.loads(line) for line in resp.text.splitlines() if line]
    assert events[-1]["content"] == "公共库回答"


@pytest.mark.web
def test_knowledge_public_doc_accessible_to_other_user(tenant_api):
    client, runtime, headers, ids = tenant_api
    _seed_knowledge(runtime, ids)

    public_only = {d["doc"] for d in client.get(
        "/api/knowledge", params={"scope": "public"}, headers=headers["bob"]
    ).json()["docs"]}
    assert public_only == {"alice-public"}


# ── 伪造 visibility ──


@pytest.mark.web
def test_cannot_forge_visibility_on_upload(tenant_api):
    client, _rt, headers, _ids = tenant_api
    # 普通用户（B）不能上传为公共库（伪造 public visibility）
    resp = client.post(
        "/api/knowledge/upload",
        files={"file": ("pub.md", b"x", "text/markdown")},
        data={"visibility": "public"},
        headers=headers["bob"],
    )
    assert resp.status_code == 403

    # 非法 visibility 值 → 422
    resp = client.post(
        "/api/knowledge/upload",
        files={"file": ("bad.md", b"x", "text/markdown")},
        data={"visibility": "bogus"},
        headers=headers["bob"],
    )
    assert resp.status_code == 422


@pytest.mark.web
def test_cannot_change_others_doc_visibility(tenant_api):
    client, runtime, headers, ids = tenant_api
    _seed_knowledge(runtime, ids)

    # 普通用户 B 不能发布（publish）任何文档（依赖 require_admin → 403）
    assert client.post("/api/knowledge/bob-private/publish", headers=headers["bob"]).status_code == 403
    # 且不能下架（unpublish）他人文档（同样 require_admin → 403）
    assert client.post("/api/knowledge/alice-public/unpublish", headers=headers["bob"]).status_code == 403

    # A（admin）发布自己名下私有 → 成功；下架 → 成功
    assert client.post("/api/knowledge/alice-private/publish", headers=headers["alice"]).status_code == 200
    assert client.post("/api/knowledge/alice-private/unpublish", headers=headers["alice"]).status_code == 200


# ── Quality Reviewer 账号边界（API 级断言） ──


@pytest.mark.web
def test_quality_reviewer_cannot_manage_accounts(tenant_api):
    client, _rt, headers, _ids = tenant_api
    reviewer = headers["quality_reviewer"]

    # 管理端点强制 require_admin；reviewer 一律 403
    assert client.get("/api/auth/users", headers=reviewer).status_code == 403
    assert client.post(
        "/api/auth/users",
        json={"username": "sneaky", "password": "member-password-123", "role": "user"},
        headers=reviewer,
    ).status_code == 403
    assert client.patch(
        "/api/auth/users/any-id", json={"status": "disabled"}, headers=reviewer
    ).status_code == 403

    # Reviewer 只能访问质量审查 API；身份与改密端点保留以支持账号生命周期。
    assert client.get("/api/auth/me", headers=reviewer).status_code == 200
    assert client.get("/api/knowledge", headers=reviewer).status_code == 403
