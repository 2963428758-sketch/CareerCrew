"""Phase 4: resume API 测试（monkeypatch vision_caller/loader）。"""
from __future__ import annotations

import io
import json

import pytest


@pytest.mark.web
def test_upload_text(client, fake_runtime, tmp_path):
    """txt 文件 -> 直接读文本。"""
    fake_runtime.upload_content = "这是一份简历文本"
    resp = client.post(
        "/api/resume/upload",
        files={"file": ("resume.txt", io.BytesIO("这是一份简历文本".encode("utf-8")), "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["doc_type"] == "text"
    assert "简历" in data["content"]


@pytest.mark.web
def test_upload_image(client, fake_runtime):
    """图片 -> read_image 视觉描述。"""
    fake_runtime.upload_content = "视觉模型识别的简历内容"
    resp = client.post(
        "/api/resume/upload",
        files={"file": ("resume.png", io.BytesIO(b"\x89PNG fake"), "image/png")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["doc_type"] == "image"
    assert data["content"] == "视觉模型识别的简历内容"


@pytest.mark.web
def test_upload_truncation(client, fake_runtime):
    """>200k 字符截断标记 truncated:true。"""
    long_text = "A" * 250_000
    fake_runtime.upload_content = long_text
    resp = client.post(
        "/api/resume/upload",
        files={"file": ("big.txt", io.BytesIO(long_text.encode()), "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["truncated"] is True
    assert data["char_count"] == 200_000


@pytest.mark.web
def test_generate_stream(client, fake_runtime):
    """简历优化流式：stage=resume + chunk + done。"""
    fake_runtime.resume_output = "优化后的简历内容"
    resp = client.post("/api/resume/generate", json={
        "user_resume": "我的简历：Java 3 年",
        "jd": "大模型应用工程师",
    })
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    assert events[0] == {"type": "stage", "stage": "resume"}
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "优化后的简历内容"
