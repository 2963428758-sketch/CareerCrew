"""知识库图片服务 API 测试（路径白名单 + 404）。"""
from __future__ import annotations

import pytest

from careercrew_api.routers import knowledge as knowledge_router


@pytest.mark.web
def test_knowledge_image_serves_file(client, fake_runtime, tmp_path, monkeypatch):
    """data/ 内的图片可通过 /api/knowledge/image 读取。"""
    monkeypatch.setattr(knowledge_router, "_DATA_ROOT", tmp_path)
    img = tmp_path / "page_001.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16)

    resp = client.get("/api/knowledge/image", params={"path": str(img)})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
    assert resp.content.startswith(b"\x89PNG")


@pytest.mark.web
def test_knowledge_image_rejects_outside_path(client, fake_runtime, tmp_path, monkeypatch):
    """data/ 目录外的路径拒绝读取（防目录穿越）。"""
    monkeypatch.setattr(knowledge_router, "_DATA_ROOT", tmp_path)
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("secret")

    resp = client.get("/api/knowledge/image", params={"path": str(outside)})
    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


@pytest.mark.web
def test_knowledge_image_missing_file(client, fake_runtime, tmp_path, monkeypatch):
    """文件不存在返回 404。"""
    monkeypatch.setattr(knowledge_router, "_DATA_ROOT", tmp_path)
    resp = client.get("/api/knowledge/image", params={"path": str(tmp_path / "nope.png")})
    assert resp.status_code == 404
