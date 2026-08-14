"""知识库 API 测试（FakeRuntime）。"""
from __future__ import annotations

import json
import time

import pytest


@pytest.fixture(autouse=True)
def _uploads_to_tmp(monkeypatch, tmp_path):
    """上传落盘改到临时目录，避免污染 data/uploads。"""
    import careercrew_api.routers.knowledge as knowledge

    monkeypatch.setattr(knowledge, "UPLOAD_DIR", tmp_path)


@pytest.mark.web
def test_knowledge_list(client, fake_runtime):
    """GET /api/knowledge -> {points, docs}。"""
    resp = client.get("/api/knowledge")
    assert resp.status_code == 200
    data = resp.json()
    assert data["points"] == 3
    assert data["docs"][0]["doc"] == "note"


@pytest.mark.web
def test_knowledge_upload(client):
    """POST /api/knowledge/upload -> 202 {job_id}，轮询 GET /upload/{job_id} 直到 done。"""
    resp = client.post(
        "/api/knowledge/upload",
        files={"file": ("note.md", "# 测试文档\n内容".encode("utf-8"), "text/markdown")},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["job_id"]
    assert data["filename"] == "note.md"
    assert data["status"] == "queued"
    assert data["progress"] == 0.0

    job = None
    for _ in range(50):
        status = client.get(f"/api/knowledge/upload/{data['job_id']}")
        assert status.status_code == 200
        job = status.json()
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.02)

    assert job is not None
    assert job["status"] == "done"
    assert job["stage"] == "done"
    assert job["progress"] == 1.0
    assert job["result"]["doc_id"] == "note"
    assert job["result"]["points"] == 2


@pytest.mark.web
def test_knowledge_upload_error(client, fake_runtime):
    """后台入库抛错时任务进入 error 状态，前端可展示错误信息。"""
    fake_runtime.ingest_error = RuntimeError("MinerU boom")
    resp = client.post(
        "/api/knowledge/upload",
        files={"file": ("bad.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = None
    for _ in range(50):
        job = client.get(f"/api/knowledge/upload/{job_id}").json()
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.02)

    assert job is not None
    assert job["status"] == "error"
    assert "MinerU boom" in job["error"]


@pytest.mark.web
def test_knowledge_upload_status_404(client):
    """未知 job_id 返回 404。"""
    resp = client.get("/api/knowledge/upload/no-such-job")
    assert resp.status_code == 404


@pytest.mark.web
def test_knowledge_delete(client):
    """DELETE /api/knowledge/{doc_id} -> {deleted, doc_id}。"""
    resp = client.delete("/api/knowledge/note")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] == 3
    assert data["doc_id"] == "note"


@pytest.mark.web
def test_knowledge_ask_done_uses_final_answer(client, fake_runtime):
    """回归：知识库流式 chunk 带中间轮开头话时，done 内容取最终回答（与落库一致）。"""
    fake_runtime.knowledge_output = "这是基于知识库的最终回答。"
    fake_runtime.stream_preamble = "好的，我先检索知识库"
    resp = client.post("/api/knowledge/ask", json={
        "question": "什么是 RAG？", "user_id": "u_001", "thread_id": "k-t1",
    })
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    chunks = "".join(e["text"] for e in events if e["type"] == "chunk")
    assert "好的，我先检索知识库" in chunks
    done = events[-1]
    assert done["type"] == "done"
    assert done["content"] == "这是基于知识库的最终回答。"
    assert done["sources"] == fake_runtime.knowledge_sources
