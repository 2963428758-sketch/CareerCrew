"""Phase 4: resume API 测试（monkeypatch vision_caller/loader + 异步上传任务）。"""
from __future__ import annotations

import io
import json
import time

import pytest


@pytest.fixture(autouse=True)
def _uploads_to_tmp(monkeypatch, tmp_path):
    """上传落盘改到临时目录，避免污染 data/uploads。"""
    from careercrew_api import storage
    from careercrew_api.storage import layout

    monkeypatch.setattr(storage, "L", layout(tmp_path / "data"))


def _poll_job(client, job_id: str, timeout: float = 5.0) -> dict:
    """轮询上传任务直到结束（done / error）。"""
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        resp = client.get(f"/api/resume/upload/{job_id}")
        assert resp.status_code == 200
        job = resp.json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} 未在 {timeout}s 内结束: {job}")


@pytest.mark.web
def test_upload_text(client, fake_runtime):
    """txt 文件 -> 异步任务 -> done，result 直接读文本。"""
    fake_runtime.upload_content = "这是一份简历文本"
    resp = client.post(
        "/api/resume/upload",
        files={"file": ("resume.txt", io.BytesIO("这是一份简历文本".encode()), "text/plain")},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["job_id"]
    assert data["filename"] == "resume.txt"
    assert data["status"] == "queued"
    assert data["progress"] == 0.0

    job = _poll_job(client, data["job_id"])
    assert job["status"] == "done"
    assert job["stage"] == "done"
    assert job["progress"] == 1.0
    assert job["result"]["doc_type"] == "text"
    assert "简历" in job["result"]["content"]
    assert job["result"]["char_count"] > 0


@pytest.mark.web
def test_upload_image(client, fake_runtime):
    """图片 -> read_image 视觉描述。"""
    fake_runtime.upload_content = "视觉模型识别的简历内容"
    resp = client.post(
        "/api/resume/upload",
        files={"file": ("resume.png", io.BytesIO(b"\x89PNG fake"), "image/png")},
    )
    assert resp.status_code == 202
    job = _poll_job(client, resp.json()["job_id"])
    assert job["status"] == "done"
    assert job["result"]["doc_type"] == "image"
    assert job["result"]["content"] == "视觉模型识别的简历内容"


@pytest.mark.web
def test_upload_truncation(client, fake_runtime):
    """>200k 字符截断标记 truncated:true。"""
    long_text = "A" * 250_000
    fake_runtime.upload_content = long_text
    resp = client.post(
        "/api/resume/upload",
        files={"file": ("big.txt", io.BytesIO(long_text.encode()), "text/plain")},
    )
    assert resp.status_code == 202
    job = _poll_job(client, resp.json()["job_id"])
    assert job["status"] == "done"
    assert job["result"]["truncated"] is True
    assert job["result"]["char_count"] == 200_000


@pytest.mark.web
def test_upload_error_job(client, fake_runtime):
    """解析抛错时任务进入 error 状态，前端可展示错误信息。"""
    fake_runtime.upload_error = RuntimeError("MinerU boom")
    resp = client.post(
        "/api/resume/upload",
        files={"file": ("bad.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 202
    job = _poll_job(client, resp.json()["job_id"])
    assert job["status"] == "error"
    # 解析错误经 _parse_resume_file 包装为中文业务异常（含格式上下文），
    # friendly_error 对中文业务信息原样透传
    assert job["error"]
    assert any("\u4e00" <= ch <= "\u9fff" for ch in job["error"])
    assert "解析失败" in job["error"]


@pytest.mark.web
def test_upload_oversize(client):
    """>20MB 直接 413（与知识库一致的 HTTP 语义）。"""
    resp = client.post(
        "/api/resume/upload",
        files={"file": ("big.pdf", io.BytesIO(b"x" * (20 * 1024 * 1024 + 1)), "application/pdf")},
    )
    assert resp.status_code == 413


@pytest.mark.web
def test_upload_status_404(client):
    """未知 job_id 返回 404。"""
    resp = client.get("/api/resume/upload/no-such-job")
    assert resp.status_code == 404


@pytest.mark.web
def test_resume_library_list_and_content(client, fake_runtime):
    """上传完成后写入简历库：列表含元数据，content 可读取原文。"""
    fake_runtime.upload_content = "库内简历：Java 3 年"
    resp = client.post(
        "/api/resume/upload",
        files={"file": ("resume.md", io.BytesIO("库内简历：Java 3 年".encode()), "text/markdown")},
    )
    assert resp.status_code == 202
    job = _poll_job(client, resp.json()["job_id"])
    resume_id = job["result"]["resume_id"]
    assert resume_id

    lib = client.get("/api/resume/library")
    assert lib.status_code == 200
    data = lib.json()
    assert data["resumes"][0]["resume_id"] == resume_id
    assert data["resumes"][0]["filename"] == "resume.md"
    assert data["resumes"][0]["doc_type"] == "text"

    content = client.get(f"/api/resume/library/{resume_id}/content")
    assert content.status_code == 200
    assert "Java 3 年" in content.json()["content"]


@pytest.mark.web
def test_resume_library_delete(client):
    """删除简历后列表与 content 均不可再访问。"""
    resp = client.post(
        "/api/resume/upload",
        files={"file": ("r.txt", io.BytesIO("简历".encode()), "text/plain")},
    )
    job = _poll_job(client, resp.json()["job_id"])
    resume_id = job["result"]["resume_id"]

    deleted = client.delete(f"/api/resume/library/{resume_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == resume_id

    assert client.get(f"/api/resume/library/{resume_id}/content").status_code == 404
    assert client.delete(f"/api/resume/library/{resume_id}").status_code == 404
    assert client.get("/api/resume/library").json()["resumes"] == []


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


@pytest.mark.web
def test_chat_stream_first_round(client, fake_runtime):
    """对话式简历优化首轮：携带简历 + 流式 done。"""
    fake_runtime.resume_output = "按 JD 定制后的简历"
    resp = client.post("/api/resume/chat", json={
        "question": "帮我针对这份 JD 优化简历",
        "resume_text": "我的简历：Java 3 年",
        "jd": "大模型应用工程师",
        "thread_id": "r-test-1",
    })
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    assert events[0] == {"type": "stage", "stage": "resume"}
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "按 JD 定制后的简历"


@pytest.mark.web
def test_chat_stream_reuses_stored_resume(client, fake_runtime, tmp_path):
    """第二轮不带 resume_text：从线程存储恢复简历，继续多轮对话。"""
    fake_runtime.resume_output = "再次优化后的简历"
    resp = client.post("/api/resume/chat", json={
        "question": "再优化一下项目经历",
        "resume_text": "我的简历：Java 3 年",
        "thread_id": "r-test-2",
    })
    assert resp.status_code == 200
    from careercrew_api.routers.resume import _resume_path

    assert _resume_path("u_001", "r-test-2").exists()

    resp2 = client.post("/api/resume/chat", json={
        "question": "再优化一下项目经历",
        "thread_id": "r-test-2",
    })
    assert resp2.status_code == 200
    events = [json.loads(l) for l in resp2.text.strip().split("\n") if l.strip()]
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "再次优化后的简历"


@pytest.mark.web
def test_chat_stream_without_resume(client, fake_runtime):
    """未上传简历：直接提问也能对话（agent 会引导上传）。"""
    fake_runtime.resume_output = "请先上传简历"
    resp = client.post("/api/resume/chat", json={
        "question": "我想优化简历",
        "thread_id": "r-test-3",
    })
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "请先上传简历"
