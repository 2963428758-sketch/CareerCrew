"""TTL 清理脚本（fake store）单元测试。

覆盖：只删 expires_at < now 且非 saved_to_knowledge 的附件；物理删文件 + DB 删行；
saved_to_knowledge / 未过期 / expires_at=NULL 一律保留。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from careercrew_core.conversation.attachments import (
    AttachmentStore,
    FakeAttachmentDb,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from cleanup_chat_attachments import cleanup_expired  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@pytest.fixture
def store() -> AttachmentStore:
    return AttachmentStore(FakeAttachmentDb())


def _seed(store, attachments_root, *, expires_at, status="uploaded", storage_key_user="u_1"):
    attachment_id = str(uuid4())
    rel = f"{storage_key_user}/t-1/{attachment_id}"
    disk = attachments_root / rel
    disk.parent.mkdir(parents=True, exist_ok=True)
    disk.write_bytes(b"x")
    # 直接写 DB（绕过 store.create 的 7 天默认 TTL，精确控制 expires_at）
    store._db.create_attachment(
        attachment_id, storage_key_user, "t-1", "f.pdf", rel,
        "application/pdf", 1, status, expires_at=expires_at,
    )
    return attachment_id


def test_cleanup_removes_expired_file_and_row(store, tmp_path):
    root = tmp_path / "attachments"
    now = datetime.now(timezone.utc)
    aid = _seed(store, root, expires_at=_iso(now - timedelta(days=1)))
    results = cleanup_expired(store, root, now=now, dry_run=False)
    assert len(results) == 1
    assert not (root / "u_1" / "t-1" / aid).exists()
    from careercrew_core.conversation.attachments import OwnershipError
    with pytest.raises(OwnershipError):
        store.get("u_1", aid)


def test_cleanup_skips_saved_to_knowledge(store, tmp_path):
    root = tmp_path / "attachments"
    now = datetime.now(timezone.utc)
    # saved_to_knowledge 即使带过期时间也保留
    _seed(store, root, expires_at=_iso(now - timedelta(days=1)), status="saved_to_knowledge")
    results = cleanup_expired(store, root, now=now, dry_run=False)
    assert results == []


def test_cleanup_skips_future_and_null(store, tmp_path):
    root = tmp_path / "attachments"
    now = datetime.now(timezone.utc)
    _seed(store, root, expires_at=_iso(now + timedelta(days=1)))
    # expires_at=NULL（已保存到知识库场景）
    _seed(store, root, expires_at=None)
    results = cleanup_expired(store, root, now=now, dry_run=False)
    assert results == []


def test_cleanup_dry_run_does_not_delete(store, tmp_path):
    root = tmp_path / "attachments"
    now = datetime.now(timezone.utc)
    aid = _seed(store, root, expires_at=_iso(now - timedelta(days=1)))
    results = cleanup_expired(store, root, now=now, dry_run=True)
    assert len(results) == 1
    assert (root / "u_1" / "t-1" / aid).exists()  # dry-run 不删文件
    # DB 行也保留
    assert store.get("u_1", aid)["id"] == aid
