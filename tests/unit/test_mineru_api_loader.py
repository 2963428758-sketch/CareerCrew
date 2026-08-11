"""MinerU 云端 API loader 契约测试（mock requests Session，不触网）。"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from careercrew_core.rag.loaders.mineru_api_loader import MinerUApiLoader
from careercrew_core.rag.loaders.mineru_common import ParsingError


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, content=b"", text=""):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = text or str(json_data or "")

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1 << 16):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeSession:
    def __init__(self, post_resp=None, put_status=200, poll_responses=None, zip_bytes=b""):
        self.post_resp = post_resp or {"code": 0, "data": {"batch_id": "b1", "file_urls": ["https://up/1"]}}
        self.put_status = put_status
        self.poll_responses = poll_responses or []
        self.zip_url = "https://cdn/result.zip"
        self.zip_bytes = zip_bytes
        self.post_calls: list[dict] = []
        self.put_calls: list[tuple[str, object]] = []
        self.get_calls: list[tuple[str, object]] = []
        self._poll_idx = 0

    def post(self, url, headers=None, json=None, timeout=None):
        self.post_calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResp(200, self.post_resp)

    def put(self, url, headers=None, data=None, timeout=None):
        self.put_calls.append((url, data))
        return _FakeResp(self.put_status)

    def get(self, url, headers=None, stream=False, timeout=None):
        self.get_calls.append((url, headers))
        if url == self.zip_url:
            return _FakeResp(200, content=self.zip_bytes)
        if self._poll_idx < len(self.poll_responses):
            resp = self.poll_responses[self._poll_idx]
            self._poll_idx += 1
            return _FakeResp(200, resp)
        return _FakeResp(200, {"code": 0, "data": []})


def _make_pdf(tmp_path: Path) -> Path:
    import pymupdf

    p = tmp_path / "resume.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "姓名：张三", fontsize=12)
    doc.save(str(p))
    doc.close()
    return p


def _make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("resume.md", "# 标题\n内容")
        zf.writestr(
            "resume_content_list.json",
            json.dumps(
                [
                    {"type": "text", "text": "姓名：张三", "bbox": [0, 0, 100, 20], "page_idx": 0},
                    {
                        "type": "image",
                        "text": "头像",
                        "img_path": "img1.jpg",
                        "bbox": [0, 20, 50, 50],
                        "page_idx": 0,
                    },
                ]
            ),
        )
        zf.writestr("images/img1.jpg", b"\xff\xd8\xff")
    return buf.getvalue()


def test_api_loader_parse_success(tmp_path, monkeypatch) -> None:
    """上传 -> 轮询 running->done -> 下载 zip -> 组装页面/对象。"""
    pdf = _make_pdf(tmp_path)
    zip_bytes = _make_zip()
    zip_url = "https://cdn/result.zip"
    session = _FakeSession(
        poll_responses=[
            {"code": 0, "data": [{"data_id": "resume", "state": "waiting-file"}]},
            {
                "code": 0,
                "data": [
                    {"data_id": "resume", "state": "done", "full_zip_url": zip_url}
                ],
            },
        ],
        zip_bytes=zip_bytes,
    )
    session.zip_url = zip_url
    monkeypatch.setattr("careercrew_core.rag.loaders.mineru_api_loader.time.sleep", lambda _: None)

    loader = MinerUApiLoader(
        tmp_path / "out",
        api_key="sk-test",
        model_version="vlm",
        poll_interval=1,
        timeout=60,
        session=session,
    )
    parsed = loader.parse(pdf)

    assert parsed.doc_id == "resume"
    assert len(parsed.pages) == 1
    assert "姓名：张三" in parsed.pages[0].markdown
    assert len(parsed.objects) == 1
    assert parsed.objects[0].image_path.endswith("img1.jpg")
    # 上传请求：Bearer token + files/data_id；轮询 2 次后命中 done
    assert session.post_calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert session.post_calls[0]["json"]["files"][0]["name"] == "resume.pdf"
    assert session.post_calls[0]["json"]["model_version"] == "vlm"
    assert len(session.get_calls) >= 3  # 2 次轮询 + 1 次 zip 下载


def test_api_loader_failed_state_raises(tmp_path, monkeypatch) -> None:
    pdf = _make_pdf(tmp_path)
    session = _FakeSession(
        poll_responses=[
            {"code": 0, "data": [{"data_id": "resume", "state": "failed", "err_msg": "格式不支持"}]}
        ]
    )
    monkeypatch.setattr("careercrew_core.rag.loaders.mineru_api_loader.time.sleep", lambda _: None)
    loader = MinerUApiLoader(tmp_path / "out", api_key="sk-test", poll_interval=1, timeout=60, session=session)
    with pytest.raises(ParsingError, match="格式不支持"):
        loader.parse(pdf)


def test_api_loader_upload_code_not_zero(tmp_path) -> None:
    pdf = _make_pdf(tmp_path)
    session = _FakeSession(post_resp={"code": 1, "msg": "token 无效"})
    loader = MinerUApiLoader(tmp_path / "out", api_key="sk-test", session=session)
    with pytest.raises(ParsingError, match="token 无效"):
        loader.parse(pdf)


def test_api_loader_requires_key(tmp_path) -> None:
    with pytest.raises(ParsingError, match="API key 未设置"):
        MinerUApiLoader(tmp_path / "out", api_key="")


def test_find_entry_list_and_dict() -> None:
    loader = MinerUApiLoader.__new__(MinerUApiLoader)
    entries = [
        {"data_id": "other", "state": "running"},
        {"data_id": "resume", "state": "done", "full_zip_url": "https://x.zip"},
    ]
    assert loader._find_entry(entries, "resume", "resume.pdf")["state"] == "done"
    by_name = {"resume.pdf": {"state": "done", "full_zip_url": "https://y.zip"}}
    assert loader._find_entry(by_name, "resume", "resume.pdf")["full_zip_url"] == "https://y.zip"
    assert loader._find_entry([], "resume", "resume.pdf") is None


def test_find_entry_extract_result_shape() -> None:
    """实测批量结果结构：data.extract_result[]（data_id + file_name）。"""
    loader = MinerUApiLoader.__new__(MinerUApiLoader)
    data = {
        "batch_id": "b1",
        "extract_result": [
            {
                "data_id": "smoke_test",
                "file_name": "smoke_test.pdf",
                "state": "done",
                "full_zip_url": "https://cdn/result.zip",
            }
        ],
    }
    entry = loader._find_entry(data, "smoke_test", "smoke_test.pdf")
    assert entry is not None
    assert entry["state"] == "done"
    assert entry["full_zip_url"] == "https://cdn/result.zip"


def test_api_loader_zip_slip_rejected(tmp_path, monkeypatch) -> None:
    pdf = _make_pdf(tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "bad")
    session = _FakeSession(
        poll_responses=[
            {
                "code": 0,
                "data": [
                    {"data_id": "resume", "state": "done", "full_zip_url": "https://cdn/result.zip"}
                ],
            }
        ],
        zip_bytes=buf.getvalue(),
    )
    monkeypatch.setattr("careercrew_core.rag.loaders.mineru_api_loader.time.sleep", lambda _: None)
    loader = MinerUApiLoader(
        tmp_path / "out", api_key="sk-test", poll_interval=1, timeout=60, session=session
    )
    with pytest.raises(ParsingError, match="非法路径"):
        loader.parse(pdf)
