"""知识库 API 测试（FakeRuntime）。"""
from __future__ import annotations

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
    """POST /api/knowledge/upload -> {filename, doc_id, points}。"""
    resp = client.post(
        "/api/knowledge/upload",
        files={"file": ("note.md", "# 测试文档\n内容".encode("utf-8"), "text/markdown")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "note.md"
    assert data["doc_id"] == "note"
    assert data["points"] == 2


@pytest.mark.web
def test_knowledge_delete(client):
    """DELETE /api/knowledge/{doc_id} -> {deleted, doc_id}。"""
    resp = client.delete("/api/knowledge/note")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] == 3
    assert data["doc_id"] == "note"
