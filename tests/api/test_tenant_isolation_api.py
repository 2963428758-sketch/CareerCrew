"""Dual-account API regressions for authentication-principal tenant isolation."""
from __future__ import annotations

import io
import json
import time

import pytest

from tests.api.conftest import FakeRuntime


PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def tenant_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from careercrew_api.auth.dependencies import get_auth_service
    from careercrew_api.auth.service import AccountStore, AuthService
    from careercrew_api.deps import get_runtime_dep
    from careercrew_api.main import create_app
    from careercrew_api.routers import knowledge, resume
    from careercrew_core.state.settings import AuthSettings

    monkeypatch.setattr(resume, "UPLOAD_DIR", tmp_path / "resume-uploads")
    monkeypatch.setattr(resume, "RESUME_STORE_DIR", tmp_path / "resume-threads")
    monkeypatch.setattr(resume, "RESUME_LIB_DIR", tmp_path / "resume-library")
    monkeypatch.setattr(knowledge, "UPLOAD_DIR", tmp_path / "knowledge-uploads")
    monkeypatch.setattr(knowledge, "_DATA_ROOT", tmp_path)

    settings = AuthSettings(
        environment="test",
        jwt_secret="tenant-isolation-test-signing-secret-with-enough-entropy",
        account_db_path=str(tmp_path / "accounts.db"),
    )
    auth = AuthService(settings, AccountStore(settings.account_db_path))
    runtime = FakeRuntime()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    client = TestClient(app)

    admin = client.post(
        "/api/auth/bootstrap", json={"username": "alice", "password": PASSWORD}
    ).json()
    admin_login = client.post(
        "/api/auth/token", json={"username": "alice", "password": PASSWORD}
    ).json()
    admin_headers = {"Authorization": f"Bearer {admin_login['access_token']}"}
    bob = client.post(
        "/api/auth/users",
        json={"username": "bob", "password": PASSWORD, "role": "user"},
        headers=admin_headers,
    ).json()
    bob_login = client.post(
        "/api/auth/token", json={"username": "bob", "password": PASSWORD}
    ).json()
    bob_headers = {"Authorization": f"Bearer {bob_login['access_token']}"}
    return client, runtime, {"alice": admin_headers, "bob": bob_headers}, {
        "alice": admin["id"], "bob": bob["id"],
    }


def _poll(client, url: str, headers: dict[str, str]) -> dict:
    for _ in range(100):
        response = client.get(url, headers=headers)
        if response.status_code != 200:
            return {"status_code": response.status_code, "detail": response.text}
        body = response.json()
        if body["status"] in {"done", "error"}:
            return body
        time.sleep(0.01)
    raise AssertionError(f"upload job did not finish: {url}")


@pytest.mark.web
def test_business_endpoints_require_authentication_and_ignore_external_user_id(tenant_api) -> None:
    client, runtime, headers, ids = tenant_api
    assert client.get("/api/threads").status_code == 401

    response = client.post(
        f"/api/chat/match?user_id={ids['alice']}",
        json={"intent": "Bob intent", "thread_id": "spoof", "user_id": ids["alice"]},
        headers=headers["bob"],
    )
    assert response.status_code == 200
    assert runtime.last_call["user_id"] == ids["bob"]


@pytest.mark.web
def test_threads_profile_and_memory_are_isolated_for_same_public_thread_id(tenant_api) -> None:
    client, runtime, headers, ids = tenant_api
    for owner, title in (("alice", "Alice private"), ("bob", "Bob private")):
        response = client.post(
            f"/api/threads?user_id={ids['bob' if owner == 'alice' else 'alice']}",
            json={"thread_id": "shared", "module": "chat", "title": title},
            headers=headers[owner],
        )
        assert response.status_code == 200

    assert client.get("/api/threads", headers=headers["alice"]).json()[0]["title"] == "Alice private"
    assert client.get("/api/threads", headers=headers["bob"]).json()[0]["title"] == "Bob private"

    client.put(
        "/api/profile?user_id=ignored",
        json={"fields": {"profile.direction": "Alice-only direction"}},
        headers=headers["alice"],
    )
    assert client.get("/api/profile", headers=headers["alice"]).json()["profile"]["direction"] == "Alice-only direction"
    assert client.get("/api/profile", headers=headers["bob"]).json()["profile"]["direction"] == ""

    runtime.record_thread_messages(ids["alice"], "alice-only", "secret", "answer")
    assert client.get(
        "/api/memory", params={"thread_id": "alice-only", "user_id": ids["alice"]},
        headers=headers["bob"],
    ).json() == []

    client.post(
        "/api/threads", json={"thread_id": "alice-exclusive", "title": "private"},
        headers=headers["alice"],
    )
    assert client.patch(
        "/api/threads/alice-exclusive", json={"title": "stolen"}, headers=headers["bob"]
    ).status_code == 404
    assert client.delete(
        "/api/threads/alice-exclusive", headers=headers["bob"]
    ).status_code == 404


@pytest.mark.web
def test_resume_upload_jobs_library_and_thread_resume_are_owner_scoped(tenant_api) -> None:
    client, _, headers, _ = tenant_api
    jobs: dict[str, dict] = {}
    for owner, text in (("alice", "Alice resume"), ("bob", "Bob resume")):
        response = client.post(
            "/api/resume/upload",
            files={"file": ("resume.txt", io.BytesIO(text.encode()), "text/plain")},
            headers=headers[owner],
        )
        jobs[owner] = response.json()
        assert response.status_code == 202
    alice_job = _poll(client, f"/api/resume/upload/{jobs['alice']['job_id']}", headers["alice"])
    bob_job = _poll(client, f"/api/resume/upload/{jobs['bob']['job_id']}", headers["bob"])
    assert alice_job["result"]["content"] == "Alice resume"
    assert bob_job["result"]["content"] == "Bob resume"
    assert client.get(
        f"/api/resume/upload/{jobs['alice']['job_id']}", headers=headers["bob"]
    ).status_code == 404

    alice_id = alice_job["result"]["resume_id"]
    bob_id = bob_job["result"]["resume_id"]
    assert [r["resume_id"] for r in client.get("/api/resume/library", headers=headers["alice"]).json()["resumes"]] == [alice_id]
    assert [r["resume_id"] for r in client.get("/api/resume/library", headers=headers["bob"]).json()["resumes"]] == [bob_id]
    assert client.get(f"/api/resume/library/{alice_id}/content", headers=headers["bob"]).status_code == 404

    for owner, text in (("alice", "Alice thread resume"), ("bob", "Bob thread resume")):
        response = client.post(
            "/api/resume/chat",
            json={"question": "optimize", "resume_text": text, "thread_id": "shared-resume"},
            headers=headers[owner],
        )
        assert response.status_code == 200
    from careercrew_api.routers.resume import _load_resume

    assert _load_resume("u_001", "shared-resume") == "Alice thread resume"
    bob_id = client.get("/api/auth/me", headers=headers["bob"]).json()["id"]
    assert _load_resume(bob_id, "shared-resume") == "Bob thread resume"


@pytest.mark.web
def test_knowledge_records_retrieval_jobs_and_images_enforce_owner(tenant_api, tmp_path) -> None:
    client, runtime, headers, ids = tenant_api
    upload_jobs = {}
    for owner, text in (("alice", "Alice knowledge"), ("bob", "Bob knowledge")):
        response = client.post(
            "/api/knowledge/upload",
            files={"file": ("same.md", text.encode(), "text/markdown")},
            headers=headers[owner],
        )
        assert response.status_code == 202
        upload_jobs[owner] = response.json()["job_id"]
    assert client.get(
        f"/api/knowledge/upload/{upload_jobs['alice']}", headers=headers["bob"]
    ).status_code == 404
    assert _poll(
        client, f"/api/knowledge/upload/{upload_jobs['alice']}", headers["alice"]
    )["status"] == "done"
    assert _poll(
        client, f"/api/knowledge/upload/{upload_jobs['bob']}", headers["bob"]
    )["status"] == "done"
    assert (tmp_path / "knowledge-uploads" / ids["alice"] / "same.md").read_text() == "Alice knowledge"
    assert (tmp_path / "knowledge-uploads" / ids["bob"] / "same.md").read_text() == "Bob knowledge"

    runtime.knowledge_docs_by_user[ids["alice"]] = [
        {"doc": "alice-doc", "source": "alice.md", "points": 2}
    ]
    runtime.knowledge_docs_by_user[ids["bob"]] = [
        {"doc": "bob-doc", "source": "bob.md", "points": 1}
    ]
    assert client.get("/api/knowledge", headers=headers["alice"]).json()["docs"][0]["doc"] == "alice-doc"
    assert client.get("/api/knowledge", headers=headers["bob"]).json()["docs"][0]["doc"] == "bob-doc"
    assert client.delete("/api/knowledge/alice-doc", headers=headers["bob"]).status_code == 404

    runtime.knowledge_output_by_user[ids["alice"]] = "Alice answer"
    runtime.knowledge_output_by_user[ids["bob"]] = "Bob answer"
    response = client.post(
        "/api/knowledge/ask",
        json={"question": "secret", "thread_id": "same", "user_id": ids["alice"]},
        headers=headers["bob"],
    )
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert events[-1]["content"] == "Bob answer"

    image = tmp_path / "owned.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nowner")
    runtime.knowledge_asset_owners[str(image.resolve())] = ids["alice"]
    assert client.get(
        "/api/knowledge/image", params={"path": str(image)}, headers=headers["alice"]
    ).status_code == 200
    assert client.get(
        "/api/knowledge/image", params={"path": str(image)}, headers=headers["bob"]
    ).status_code == 404
