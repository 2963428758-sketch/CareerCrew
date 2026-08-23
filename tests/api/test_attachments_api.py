"""附件 API 测试（T3.1 §34）：上传/列表/删除/下载/跨用户 404/每 turn 5 个限制。

用 FakeRuntime + FakeAttachmentDb + tmp 布局；上传落盘到 storage.L.attachments
（monkeypatch 注入）。鉴权用真实的 get_current_user override（u_001）或 tenant_api。
"""
from __future__ import annotations

import time

import pytest

from careercrew_core.conversation.attachments import (
    AttachmentStore,
    FakeAttachmentDb,
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


def test_upload_bounded_read_no_full_buffer():
    """>25MB 上传走分块读取，拒绝前不会把整份内容缓冲进内存。"""
    import asyncio

    from careercrew_api.upload_io import read_bounded
    from careercrew_core.conversation.validation import MAX_ATTACHMENT_SIZE

    # 模拟超大流：每次按请求给足，总长 100MB；记录单次最大读取量。
    class FakeSpool:
        def __init__(self, total: int) -> None:
            self._total = total
            self._pos = 0
            self.max_single_read = 0

        async def read(self, n: int = -1) -> bytes:
            self.max_single_read = max(self.max_single_read, n)
            if n < 0:
                n = self._total - self._pos
            take = min(n, self._total - self._pos)
            chunk = b"x" * take
            self._pos += take
            return chunk

    file = FakeSpool(total=100 * 1024 * 1024)
    result = asyncio.run(read_bounded(file, MAX_ATTACHMENT_SIZE))
    # 拒绝：返回 None；单次读取从未超过 1MB 分块（即未一次性缓冲整份 100MB）。
    assert result is None
    assert file.max_single_read <= 1024 * 1024


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


# ── save-to-knowledge（T3.3）：状态机 + 异步解析 + 入库 ──


def test_save_to_knowledge_returns_202_and_marks_parsing(attach_client):
    client, rt, lay = attach_client
    up = _upload(client).json()
    resp = client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "parsing"


def test_save_uploaded_pdf_reaches_saved_to_knowledge(attach_client):
    """uploaded -> parsing(202) -> (后台解析) -> saved_to_knowledge + expires_at 取消。

    通过 FakeRuntime.ingest_document 注入；失败前状态通过轮询 list 观察。
    """
    client, rt, lay = attach_client
    up = _upload(client).json()
    resp = client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    assert resp.status_code == 202
    # 后台线程执行（daemon）；轮询等待其完成（saved_to_knowledge）
    _wait_status(client, "t-1", up["id"], {"saved_to_knowledge"}, timeout=5.0)
    row = client.get("/api/chat/attachments", params={"thread_id": "t-1"}).json()[0]
    assert row["status"] == "saved_to_knowledge"
    assert row["expires_at"] is None
    assert row["knowledge_document_id"]
    # 知识库入库调用覆盖：path/owner/visibility/title + category 自动识别（空串）
    assert len(rt.ingest_calls) == 1
    call = rt.ingest_calls[0]
    assert call["user_id"] == "u_001"
    assert call["visibility"] == "private"
    assert call["doc_name"] == "报告.pdf"
    assert call["category"] == ""  # 空串触发 ingest_document 自动分类（不硬编码 knowledge）


def _wait_status(client, thread_id, attachment_id, terminal, timeout=5.0, interval=0.02):
    """轮询 list 直到附件进入 terminal 状态（或超时失败）。"""
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        for row in client.get("/api/chat/attachments", params={"thread_id": thread_id}).json():
            if row["id"] == attachment_id:
                status = row["status"]
                break
        if status in terminal:
            return status
        time.sleep(interval)
    raise AssertionError(f"附件 {attachment_id} 未在 {timeout}s 内进入 {terminal}（当前 {status}）")


def test_save_md_txt_fast_path_no_pipeline(attach_client, monkeypatch):
    """md/txt 快速路径：直接 MarkdownLoader 读文本 + 入库，不触发 ingest_pipeline。

    通过注入 knowledge 路由使用的 ingest_document 验证 md/txt 走『文本直读』而非 MinerU：
    这里断言 ingest_document 收到 doc_name 且文件为 .md（pipeline 内部再路由 md→markdown）。
    """
    client, rt, lay = attach_client
    up = _upload(client, filename="note.md", content="# 标题\n\n正文内容".encode(),
                 mime="text/markdown").json()
    resp = client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    assert resp.status_code == 202
    _wait_status(client, "t-1", up["id"], {"saved_to_knowledge"}, timeout=5.0)
    # md 路径同样完成入库（doc_name=note.md），Fast path 由 ingest_document 内部 md→MarkdownLoader
    assert len(rt.ingest_calls) == 1
    assert rt.ingest_calls[0]["doc_name"] == "note.md"


def test_save_failure_sets_failed_and_parser_error(attach_client):
    client, rt, lay = attach_client
    rt.ingest_error = RuntimeError("MinerU 解析失败：模型不可用")
    up = _upload(client).json()
    resp = client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    assert resp.status_code == 202
    _wait_status(client, "t-1", up["id"], {"failed"}, timeout=5.0)
    row = client.get("/api/chat/attachments", params={"thread_id": "t-1"}).json()[0]
    assert row["status"] == "failed"
    assert "MinerU 解析失败" in (row["parser_error"] or "")


def test_save_failed_can_retry(attach_client):
    """failed 状态允许重试：failed -> parsing -> saved_to_knowledge，且成功清空 parser_error。"""
    client, rt, lay = attach_client
    rt.ingest_error = RuntimeError("第一次失败")
    up = _upload(client).json()
    client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    _wait_status(client, "t-1", up["id"], {"failed"}, timeout=5.0)
    # 清除错误，重试
    rt.ingest_error = None
    resp = client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    assert resp.status_code == 202
    _wait_status(client, "t-1", up["id"], {"saved_to_knowledge"}, timeout=5.0)
    row = client.get("/api/chat/attachments", params={"thread_id": "t-1"}).json()[0]
    assert row["status"] == "saved_to_knowledge"
    assert row["expires_at"] is None
    # 成功重试后不得残留上一次失败的 parser_error
    assert row["parser_error"] is None


def test_save_retry_success_clears_stale_parser_error(attach_client):
    """important-3 回归：失败（parser_error 已写）→ 重试成功 → GET 无 parser_error。"""
    client, rt, lay = attach_client
    up = _upload(client).json()
    # 第一次：注入解析异常 → failed + parser_error
    rt.ingest_error = RuntimeError("第一次解析失败")
    client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    _wait_status(client, "t-1", up["id"], {"failed"}, timeout=5.0)
    row = client.get("/api/chat/attachments", params={"thread_id": "t-1"}).json()[0]
    assert row["status"] == "failed"
    assert row["parser_error"] is not None

    # 第二次：清除异常 → 成功，parser_error 必须被清空
    rt.ingest_error = None
    client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    _wait_status(client, "t-1", up["id"], {"saved_to_knowledge"}, timeout=5.0)
    row = client.get("/api/chat/attachments", params={"thread_id": "t-1"}).json()[0]
    assert row["status"] == "saved_to_knowledge"
    assert row["parser_error"] is None


def test_save_ready_can_be_saved(attach_client):
    """ready 状态（已解析未入库）也允许 save。"""
    client, rt, lay = attach_client
    up = _upload(client).json()
    rt.attachment_store.update_status("u_001", up["id"], "ready")
    resp = client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    assert resp.status_code == 202


def test_save_requires_ownership(tenant_api, tmp_path, monkeypatch):
    """跨用户：bob 不能把 alice 的附件存入知识库（404）。"""
    from careercrew_api import storage
    from careercrew_api.storage import layout

    monkeypatch.setattr(storage, "L", layout(tmp_path / "data"))
    client, rt, headers, ids = tenant_api
    up = client.post(
        "/api/chat/attachments",
        files={"file": ("a.pdf", PDF, "application/pdf")},
        data={"thread_id": "t-1"},
        headers=headers["alice"],
    ).json()
    resp = client.post(
        f"/api/chat/attachments/{up['id']}/save-to-knowledge", headers=headers["bob"]
    )
    assert resp.status_code == 404


def test_save_already_saved_noop_conflict(attach_client):
    """saved_to_knowledge 已入库时重复请求返回 409，不改写状态。"""
    client, rt, lay = attach_client
    up = _upload(client).json()
    client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    _wait_status(client, "t-1", up["id"], {"saved_to_knowledge"}, timeout=5.0)
    resp = client.post(f"/api/chat/attachments/{up['id']}/save-to-knowledge")
    assert resp.status_code == 409
