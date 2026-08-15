"""附件 API 测试（T3.1 §34）：上传/列表/删除/下载/跨用户 404/每 turn 5 个限制。

用 FakeRuntime + FakeAttachmentDb + tmp 布局；上传落盘到 storage.L.attachments
（monkeypatch 注入）。鉴权用真实的 get_current_user override（u_001）或 tenant_api。
"""
from __future__ import annotations

import pytest

from careercrew_core.conversation.attachments import (
    FakeAttachmentDb,
    AttachmentStore,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PDF = b"%PDF-1.7" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
ZIP = b"PK\x03\x04" + b"\x00" * 16


@pytest.fixture
def attach_client(client, fake_runtime, tmp_path, monkeypatch):
    """把 storage.L 换成 tmp 布局，并给 FakeRuntime 装上 FakeAttachmentDb 的 store。"""
    from careercrew_api import storage
    from careercrew_api.storage import layout

    lay = layout(tmp_path / "data")
    monkeypatch.setattr(storage, "L", lay)
    fake_runtime.attachment_store = AttachmentStore(FakeAttachmentDb())
    return client, fake_runtime, lay


# ── 上传成功 / 拒绝 ──

def test_upload_success(attach_client):
    client, rt, lay = attach_client
    resp = client.post(
        "/api/chat/attachments",
        files={"file": ("报告.pdf", PDF, "application/pdf")},
        data={"thread_id": "t-1"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["original_filename"] == "报告.pdf"
    assert body["mime_type"] == "application/pdf"
    assert body["status"] == "uploaded"
    # 落盘在 attachments/{user}/{thread}/{uuid}，不含原文件名
    uid = "u_001"
    files = list((lay.attachments / uid / "t-1").glob("*"))
    assert len(files) == 1
    assert files[0].name != "报告.pdf"


def test_upload_rejects_textfile_disguised_as_pdf(attach_client):
    client, rt, lay = attach_client
    resp = client.post(
        "/api/chat/attachments",
        files={"file": ("x.pdf", b"plain text not a pdf", "application/pdf")},
        data={"thread_id": "t-1"},
    )
    assert resp.status_code == 422


def test_upload_rejects_oversize(attach_client):
    client, rt, lay = attach_client
    big = b"A" * (25 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/chat/attachments",
        files={"file": ("big.txt", big, "text/plain")},
        data={"thread_id": "t-1"},
    )
    assert resp.status_code == 413


def test_upload_rejects_unknown_extension(attach_client):
    client, rt, lay = attach_client
    resp = client.post(
        "/api/chat/attachments",
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
        data={"thread_id": "t-1"},
    )
    assert resp.status_code == 422


# ── 列表 / 下载 / 删除 ──

def _upload(client, thread_id="t-1", filename="报告.pdf", content=PDF, mime="application/pdf"):
    return client.post(
        "/api/chat/attachments",
        files={"file": (filename, content, mime)},
        data={"thread_id": thread_id},
    )


def test_list_returns_metadata_no_content(attach_client):
    client, rt, lay = attach_client
    _upload(client)
    resp = client.get("/api/chat/attachments", params={"thread_id": "t-1"})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["original_filename"] == "报告.pdf"
    assert "id" in row
    assert "storage_key" not in row  # 不泄露磁盘路径
    assert "content" not in row


def test_download_content_owned(attach_client):
    client, rt, lay = attach_client
    up = _upload(client).json()
    resp = client.get(f"/api/chat/attachments/{up['id']}/content")
    assert resp.status_code == 200
    assert resp.content == PDF


def test_delete_removes_row_and_file(attach_client):
    client, rt, lay = attach_client
    up = _upload(client).json()
    files_before = list((lay.attachments / "u_001" / "t-1").glob("*"))
    assert len(files_before) == 1
    resp = client.delete(f"/api/chat/attachments/{up['id']}")
    assert resp.status_code == 200
    assert list((lay.attachments / "u_001" / "t-1").glob("*")) == []


# ── 每 turn 5 个限制 ──

def test_per_turn_limit_five(attach_client):
    client, rt, lay = attach_client
    for i in range(5):
        r = _upload(client, filename=f"f{i}.pdf")
        assert r.status_code == 201, r.text
    sixth = _upload(client, filename="f6.pdf")
    assert sixth.status_code == 422  # 每 turn 5 个限制


# ── 跨用户 404 ──

def test_cross_user_list_delete_content_isolated(tenant_api, tmp_path, monkeypatch):
    from careercrew_api import storage
    from careercrew_api.storage import layout

    lay = layout(tmp_path / "data")
    monkeypatch.setattr(storage, "L", lay)
    client, rt, headers, ids = tenant_api
    rt.attachment_store = AttachmentStore(FakeAttachmentDb())

    up = client.post(
        "/api/chat/attachments",
        files={"file": ("a.pdf", PDF, "application/pdf")},
        data={"thread_id": "t-1"},
        headers=headers["alice"],
    ).json()

    # bob 不可见 alice 的附件
    assert client.get("/api/chat/attachments", params={"thread_id": "t-1"},
                      headers=headers["bob"]).json() == []
    assert client.get(f"/api/chat/attachments/{up['id']}/content",
                      headers=headers["bob"]).status_code == 404
    assert client.delete(f"/api/chat/attachments/{up['id']}",
                         headers=headers["bob"]).status_code == 404

    # alice 仍可见
    assert client.get("/api/chat/attachments", params={"thread_id": "t-1"},
                      headers=headers["alice"]).json()[0]["id"] == up["id"]


# ── save-to-knowledge 501 ──

def test_save_to_knowledge_not_implemented(attach_client):
    client, rt, lay = attach_client
    up = _upload(client).json()
    resp = client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    assert resp.status_code == 501
