import importlib
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.preparation_fakes import SqlitePreparationPool


@pytest.fixture
def prep_api():
    try:
        routes = importlib.import_module("careercrew_api.routers.preparation")
        stores = importlib.import_module("careercrew_core.preparation.store")
    except ModuleNotFoundError:
        yield None
        return
    from careercrew_api.auth.dependencies import get_current_user
    pool = SqlitePreparationPool()
    store = stores.PreparationStore(pool=pool)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/preparation")
    identity = {"id": "alice", "role": "user"}
    app.dependency_overrides[get_current_user] = lambda: identity
    app.dependency_overrides[routes.get_preparation_store] = lambda: store
    with TestClient(app) as client:
        yield client, identity, store
    pool.close()


JOB = {"company": "测试公司", "title": "Java开发", "jd": "负责接口开发"}


def create_job(client):
    response = client.post("/api/preparation/opportunities", json=JOB)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize("field,value", [
    ("company", " "), ("title", ""), ("jd", "\n"), ("jd", "文" * 30001),
    ("company", "x" * 201), ("salary", "x" * 201), ("source", "x" * 101),
    ("url", "javascript:alert(1)"), ("url", "file:///private"), ("url", "https://"),
    ("url", "https://example.com/\r\nheader"), ("url", "//example.com"),
    ("owner_id", "bob"),
], ids=["blank-company", "empty-title", "blank-jd", "large-jd", "large-company", "large-salary", "large-source", "javascript", "file", "missing-host", "control-url", "relative-url", "owner-injection"])
def test_input_validation_and_owner_injection(prep_api, field, value):
    assert prep_api is not None, "岗位准备 API 尚未实现"
    client, _, store = prep_api
    response = client.post("/api/preparation/opportunities", json={**JOB, field: value})
    assert response.status_code == 422
    assert store.list_opportunities("alice") == []


def test_crud_versions_sessions_exports_are_scoped(prep_api):
    assert prep_api is not None, "岗位准备 API 尚未实现"
    client, identity, _ = prep_api
    oid = create_job(client)
    base = f"/api/preparation/opportunities/{oid}"
    assert client.get(base).json()["jd"] == "负责接口开发"
    response = client.post(base + "/versions", json={
        "label": "中文简历", "content": "完整简历内容", "original_content": "上传原文"})
    assert response.status_code == 201
    vid = response.json()["id"]
    assert client.get(base + "/versions").json()[0]["id"] == vid
    session = client.post(base + "/sessions", json={
        "module": "interview", "resume_version_id": vid}).json()
    tid = session["thread_id"]
    assert tid.startswith("i-prep-")
    for fmt, mime in [("pdf", "application/pdf"), ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")]:
        result = client.get(base + f"/versions/{vid}/export?format={fmt}")
        assert result.status_code == 200
        assert result.headers["content-type"] == mime
        assert "中文简历" in unquote(result.headers["content-disposition"])
        assert result.headers["cache-control"] == "private, no-store"
    assert client.put(base, json={**JOB, "jd": "后来修改"}).status_code == 200
    assert client.get(f"/api/preparation/sessions/{tid}").json()["jd"] == "负责接口开发"
    identity["id"] = "bob"
    assert client.get("/api/preparation/opportunities").json() == []
    for suffix in ["", "/versions", f"/versions/{vid}/export?format=pdf", f"/versions/{vid}/export?format=docx"]:
        assert client.get(base + suffix).status_code == 404
    assert client.put(base, json=JOB).status_code == 404
    assert client.delete(base).status_code == 404
    assert client.post(base + "/versions", json={"label": "盗用", "content": "正文"}).status_code == 404
    assert client.post(base + "/sessions", json={"module": "resume", "resume_version_id": vid}).status_code == 404
    assert client.get(f"/api/preparation/sessions/{tid}").status_code == 404
    identity["id"] = "alice"
    assert client.delete(base).json() == {"ok": True}
    assert client.get(f"/api/preparation/sessions/{tid}").status_code == 404


def test_version_and_session_validation(prep_api):
    assert prep_api is not None, "岗位准备 API 尚未实现"
    client, _, _ = prep_api
    oid = create_job(client)
    base = f"/api/preparation/opportunities/{oid}"
    for payload in [{"label": "", "content": "text"}, {"label": "版本", "content": " "},
                    {"label": "版本", "content": "x" * 50001}]:
        assert client.post(base + "/versions", json=payload).status_code == 422
    assert client.post(base + "/sessions", json={"module": "chat", "resume_version_id": "missing"}).status_code == 422
    assert client.post(base + "/sessions", json={"module": "resume", "resume_version_id": "missing"}).status_code == 404
    assert client.get(base + "/versions/missing/export?format=html").status_code == 422


@pytest.fixture
def prep_store(client, monkeypatch):
    """把 preparation_context 与 prep 路由的存储都替换为 SQLite 测试池。

    路由的 Depends 绑定在导入期的函数对象上，因此 prep 路由走 dependency_overrides，
    preparation_context（普通函数调用）走 monkeypatch。
    """
    import careercrew_api.preparation_context as pc
    import careercrew_api.routers.preparation as prep_router
    from careercrew_core.preparation.store import PreparationStore

    store = PreparationStore(pool=SqlitePreparationPool())
    monkeypatch.setattr(pc, "get_preparation_store", lambda: store)
    client.app.dependency_overrides[prep_router.get_preparation_store] = lambda: store
    yield store
    client.app.dependency_overrides.pop(prep_router.get_preparation_store, None)
    return store


def _create_session(client, module="resume"):
    oid = create_job(client)
    resp = client.post(f"/api/preparation/opportunities/{oid}/versions",
                       json={"label": "快照版本", "content": "快照简历正文", "original_content": "原文"})
    assert resp.status_code == 201
    vid = resp.json()["id"]
    resp = client.post(f"/api/preparation/opportunities/{oid}/sessions",
                       json={"module": module, "resume_version_id": vid})
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.web
def test_resume_chat_injects_prepared_snapshot(client, fake_runtime, prep_store, monkeypatch):
    """r-prep- 会话：每轮注入快照 JD/简历；普通线程行为不变。"""
    session = _create_session(client, module="resume")
    assert session["thread_id"].startswith("r-prep-")

    captured = {}
    original_new = fake_runtime.new_resume_advisor

    def spy_new(*args, **kwargs):
        agent = original_new(*args, **kwargs)
        inner_run = agent.run

        def run(state):
            captured["intent"] = state.get("user_intent")
            return inner_run(state)

        agent.run = run
        return agent

    monkeypatch.setattr(fake_runtime, "new_resume_advisor", spy_new)

    resp = client.post("/api/resume/chat", json={
        "thread_id": session["thread_id"], "question": "请针对岗位优化这段经历"})
    assert resp.status_code == 200, resp.text
    events = [line for line in resp.text.strip().split("\n") if line.strip()]
    assert events[-1].startswith("{\"type\":\"done\"") or "\"type\": \"done\"" in events[-1]
    # 注入的是快照内容（JD + 简历版本），用户问题保持可读
    assert "快照简历正文" in captured["intent"]
    assert "负责接口开发" in captured["intent"]
    assert "请针对岗位优化这段经历" in captured["intent"]


@pytest.mark.web
def test_prepared_session_wrong_owner_or_module_is_404(client, fake_runtime, prep_store, monkeypatch):
    """跨账号读取与模块不匹配一律 404；普通线程不受 prep 校验影响。"""
    session = _create_session(client, module="interview")

    from careercrew_api.auth.dependencies import get_current_user

    client.app.dependency_overrides[get_current_user] = lambda: {"id": "bob", "role": "user"}
    resp = client.post("/api/interview/chat", json={"thread_id": session["thread_id"], "messages": []})
    client.app.dependency_overrides[get_current_user] = lambda: {"id": "u_001", "role": "admin"}
    assert resp.status_code == 404

    # resume 模块的聊天端点访问 i-prep- 会话 → 模块不匹配 → 404
    resp = client.post("/api/resume/chat", json={"thread_id": session["thread_id"], "question": "hi"})
    assert resp.status_code == 404

    # 普通线程不受影响（无准备会话，仍走原路径）
    resp = client.post("/api/resume/chat", json={"thread_id": "t-normal", "question": "hi",
                                                 "resume_text": "我的简历"})
    assert resp.status_code == 200, resp.text


@pytest.mark.web
def test_interview_chat_injects_prepared_snapshot(client, fake_runtime, prep_store, monkeypatch):
    """i-prep- 会话：面试对话注入岗位与简历快照。"""
    session = _create_session(client, module="interview")

    captured = {}
    original_new = fake_runtime.new_interviewer

    def spy_new(*args, **kwargs):
        agent = original_new(*args, **kwargs)
        inner_run = agent.run

        def run(state):
            messages = state.get("messages") or []
            captured["content"] = getattr(messages[0], "content", "") if messages else ""
            return inner_run(state)

        agent.run = run
        return agent

    monkeypatch.setattr(fake_runtime, "new_interviewer", spy_new)

    resp = client.post("/api/interview/chat", json={
        "thread_id": session["thread_id"],
        "messages": [{"role": "user", "content": "请开始面试"}],
    })
    assert resp.status_code == 200, resp.text
    assert "快照简历正文" in captured["content"]
    assert "负责接口开发" in captured["content"]
    assert "请开始面试" in captured["content"]
