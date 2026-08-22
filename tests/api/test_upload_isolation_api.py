"""上传隔离 API 回归测试：同名隔离、简历不入知识库、越界 404、跨用户 404。

FakeRuntime 的 ingest_document 会记录调用（ingest_calls）；raw 目录写入由
monkeypatch 把 storage.L 换成 tmp 布局后验证路径结构（路由经模块属性引用）。
"""
from __future__ import annotations

import json
import re

import pytest


@pytest.fixture
def tenant_api(tmp_path, monkeypatch):
    """双账号客户端（模式同 test_tenant_isolation_api.tenant_api）。"""
    from fastapi.testclient import TestClient

    from careercrew_api import storage
    from careercrew_api.auth.dependencies import get_auth_service
    from careercrew_api.auth.service import AuthService
    from careercrew_api.deps import get_runtime_dep
    from careercrew_api.main import create_app
    from careercrew_api.storage import layout
    from careercrew_core.state.settings import AuthSettings
    from tests.api.conftest import FakeRuntime
    from tests.fakes import FakeAccountStore

    monkeypatch.setattr(storage, "L", layout(tmp_path / "data"))
    settings = AuthSettings(
        environment="test",
        jwt_secret="upload-isolation-test-signing-secret-with-enough-entropy",
    )
    auth = AuthService(settings, FakeAccountStore())
    runtime = FakeRuntime()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    client = TestClient(app)

    password = "correct-horse-battery-staple"
    bob_password = "bob-password-123"
    admin = client.post(
        "/api/auth/bootstrap", json={"username": "alice", "password": password}
    ).json()
    admin_login = client.post(
        "/api/auth/token", json={"username": "alice", "password": password}
    ).json()
    admin_headers = {"Authorization": f"Bearer {admin_login['access_token']}"}
    client.post(
        "/api/auth/users", json={"username": "bob", "password": bob_password, "role": "user"},
        headers=admin_headers,
    )
    bob_login = client.post(
        "/api/auth/token", json={"username": "bob", "password": bob_password}
    ).json()
    # 管理员显式设密 => 无强制改密标记，直接登录可用
    bob_headers = {"Authorization": f"Bearer {bob_login['access_token']}"}
    return client, runtime, {"alice": admin_headers, "bob": bob_headers}, {
        "alice": admin["id"], "bob": bob_login["user"]["id"],
    }


def test_same_filename_two_users_isolated(tenant_api, tmp_path):
    from careercrew_api import storage

    client, _runtime, headers, ids = tenant_api
    lay = storage.L  # tenant_api 已注入 tmp 布局

    alice_job = client.post(
        "/api/knowledge/upload",
        files={"file": ("面试题.pdf", b"alice-bytes", "application/pdf")},
        headers=headers["alice"],
    ).json()
    bob_job = client.post(
        "/api/knowledge/upload",
        files={"file": ("面试题.pdf", b"bob-bytes", "application/pdf")},
        headers=headers["bob"],
    ).json()

    assert alice_job["job_id"] != bob_job["job_id"]
    alice_files = list((lay.knowledge_raw / ids["alice"]).glob("*"))
    bob_files = list((lay.knowledge_raw / ids["bob"]).glob("*"))
    assert len(alice_files) == 1 and len(bob_files) == 1
    assert alice_files[0].name != bob_files[0].name
    # 原文件名不进入磁盘路径（UUID 键名）
    assert all("面试题" not in f.name for f in alice_files + bob_files)
    # job 元数据保留原文件名
    assert alice_job["filename"] == "面试题.pdf"
    # 任务状态互不可见
    assert client.get(f"/api/knowledge/upload/{alice_job['job_id']}",
                      headers=headers["bob"]).status_code == 404


def test_resume_upload_does_not_ingest_knowledge(client, fake_runtime, tmp_path, monkeypatch):
    from careercrew_api import storage

    lay = storage.layout(tmp_path / "data")
    monkeypatch.setattr(storage, "L", lay)
    fake_runtime.ingest_calls = []

    resp = client.post(
        "/api/resume/upload",
        files={"file": ("我的简历.pdf", b"resume-bytes", "application/pdf")},
    )
    assert resp.status_code == 202
    # FakeRuntime 的解析/入库不会真实执行：这里断言知识库 ingest 未被调用
    assert fake_runtime.ingest_calls == []
    # 简历原件落在 resumes_raw 而非 knowledge_raw
    assert (lay.resumes_raw / "u_001").exists()


def test_library_traversal_rejected(client):
    from careercrew_api.routers.resume import _resume_lib_dir

    assert client.get("/api/resume/library/not-a-valid-id/content").status_code == 404
    assert client.delete("/api/resume/library/not-a-valid-id").status_code == 404
    # 路径穿越/非法 resume_id 在路径构造层直接拒绝（越界 ID 永不触盘）
    for bad in ("../x", "..", "x" * 13, "A" * 12, "a1b2c3d4e5f6/../x"):
        with pytest.raises(ValueError):
            _resume_lib_dir("u_001", bad)


def test_library_isolated_between_users(tenant_api, tmp_path):
    from careercrew_api import storage

    client, _runtime, headers, ids = tenant_api
    lay = storage.L

    resume_id = "a1b2c3d4e5f6"
    lib_dir = lay.parsed_resumes / ids["alice"] / resume_id
    lib_dir.mkdir(parents=True)
    (lib_dir / "content.txt").write_text("alice 简历", encoding="utf-8")
    (lib_dir / "meta.json").write_text(json.dumps({
        "resume_id": resume_id, "user_id": ids["alice"], "filename": "a.pdf",
    }, ensure_ascii=False), encoding="utf-8")

    assert client.get(f"/api/resume/library/{resume_id}/content",
                      headers=headers["alice"]).json()["content"] == "alice 简历"
    assert client.get(f"/api/resume/library/{resume_id}/content",
                      headers=headers["bob"]).status_code == 404
    assert client.delete(f"/api/resume/library/{resume_id}",
                         headers=headers["bob"]).status_code == 404
    assert client.delete(f"/api/resume/library/{resume_id}",
                         headers=headers["alice"]).status_code == 200


def test_knowledge_upload_output_dir_scoped(client, fake_runtime, tmp_path, monkeypatch):
    from careercrew_api import storage

    lay = storage.layout(tmp_path / "data")
    monkeypatch.setattr(storage, "L", lay)
    fake_runtime.ingest_calls = []

    job = client.post(
        "/api/knowledge/upload",
        files={"file": ("笔记.md", "# 标题\n内容".encode(), "text/markdown")},
    ).json()
    assert job["status"] == "queued"
    # 上传路径在 knowledge_raw/{user}/{uuid}.md 内
    raw_files = list((lay.knowledge_raw / "u_001").glob("*.md"))
    assert len(raw_files) == 1
    assert re.fullmatch(r"[0-9a-f]{12}\.md", raw_files[0].name)
