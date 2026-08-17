"""AttachmentDb + AttachmentStore 单元测试（FakeAttachmentDb）。

契约对齐 conversation/db.py 的 Fake+PG 范式。覆盖 create/get/list by thread/
update status/delete/expire(TTL) 清理，以及 store 层的所有权拒绝。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from careercrew_core.conversation.attachments import (
    AttachmentDb,
    FakeAttachmentDb,
    AttachmentStore,
    OwnershipError,
)

# 状态全集（§14.3）
ALL_STATUSES = {
    "uploading", "uploaded", "parsing", "ready", "failed", "deleted",
    "saved_to_knowledge",
}


def _uuid() -> str:
    return str(uuid4())


@pytest.fixture
def db() -> FakeAttachmentDb:
    return FakeAttachmentDb()


@pytest.fixture
def store(db) -> AttachmentStore:
    return AttachmentStore(db)


def _db_kwargs(**overrides):
    base = {
        "attachment_id": _uuid(),
        "user_id": "u_1",
        "thread_id": _uuid(),
        "original_filename": "报告.pdf",
        "storage_key": "users/u_1/threads/t1/attachments/x",
        "mime_type": "application/pdf",
        "size_bytes": 100,
        "status": "uploaded",
    }
    base.update(overrides)
    return base


def _store_kwargs(**overrides):
    # store.create 生成自己的 id；不含 attachment_id/status/expires_at
    base = {
        "thread_id": _uuid(),
        "user_id": "u_1",
        "original_filename": "报告.pdf",
        "storage_key": "users/u_1/threads/t1/attachments/x",
        "mime_type": "application/pdf",
        "size_bytes": 100,
    }
    base.update(overrides)
    return base


# ── DB 层：create / get / list ──

def test_create_and_get_roundtrip(db):
    kw = _db_kwargs()
    db.create_attachment(**kw)
    row = db.get_attachment("u_1", kw["attachment_id"])
    assert row["original_filename"] == "报告.pdf"
    assert row["storage_key"] == kw["storage_key"]
    assert row["mime_type"] == "application/pdf"
    assert row["size_bytes"] == 100
    assert row["status"] == "uploaded"


def test_get_attachment_cross_user_returns_none(db):
    kw = _db_kwargs(user_id="u_1")
    db.create_attachment(**kw)
    assert db.get_attachment("u_2", kw["attachment_id"]) is None


def test_list_by_thread_scoped_to_user(db):
    tid = _uuid()
    db.create_attachment(**_db_kwargs(user_id="u_1", thread_id=tid))
    db.create_attachment(**_db_kwargs(user_id="u_1", thread_id=tid))
    db.create_attachment(**_db_kwargs(user_id="u_1", thread_id=_uuid()))
    db.create_attachment(**_db_kwargs(user_id="u_2", thread_id=tid))
    rows = db.list_attachments("u_1", tid)
    assert len(rows) == 2


def test_list_by_thread_excludes_deleted_status(db):
    tid = _uuid()
    db.create_attachment(**_db_kwargs(user_id="u_1", thread_id=tid))
    db.create_attachment(**_db_kwargs(user_id="u_1", thread_id=tid, status="deleted"))
    rows = db.list_attachments("u_1", tid)
    assert len(rows) == 1
    assert all(r["status"] != "deleted" for r in rows)


def test_update_status(db):
    kw = _db_kwargs()
    db.create_attachment(**kw)
    db.update_status("u_1", kw["attachment_id"], "parsing", parser_error=None)
    assert db.get_attachment("u_1", kw["attachment_id"])["status"] == "parsing"


def test_update_status_cross_user_noop(db):
    kw = _db_kwargs(user_id="u_1")
    db.create_attachment(**kw)
    db.update_status("u_2", kw["attachment_id"], "parsing")
    assert db.get_attachment("u_1", kw["attachment_id"])["status"] == "uploaded"


def test_delete_attachment(db):
    kw = _db_kwargs()
    db.create_attachment(**kw)
    assert db.delete_attachment("u_1", kw["attachment_id"]) is True
    assert db.get_attachment("u_1", kw["attachment_id"]) is None


def test_delete_attachment_cross_user(db):
    kw = _db_kwargs(user_id="u_1")
    db.create_attachment(**kw)
    assert db.delete_attachment("u_2", kw["attachment_id"]) is False
    assert db.get_attachment("u_1", kw["attachment_id"]) is not None


def test_count_nondeleted_per_thread(db):
    tid = _uuid()
    db.create_attachment(**_db_kwargs(user_id="u_1", thread_id=tid))
    db.create_attachment(**_db_kwargs(user_id="u_1", thread_id=tid))
    db.create_attachment(**_db_kwargs(user_id="u_1", thread_id=tid, status="deleted"))
    assert db.count_nondeleted("u_1", tid) == 2


# ── DB 层：TTL / expire ──

def test_list_expired_returns_past_expires_at(db):
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=1)
    future = now + timedelta(days=1)
    db.create_attachment(**_db_kwargs(expires_at=past))
    db.create_attachment(**_db_kwargs(expires_at=future))
    db.create_attachment(**_db_kwargs(expires_at=None))
    # 使用可注入 now 的 store 方法以确定性测试
    store = AttachmentStore(db)
    expired = store.expired_attachments(now=now)
    assert len(expired) == 1


def test_expire_skips_saved_to_knowledge(db):
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=1)
    db.create_attachment(**_db_kwargs(expires_at=past, status="saved_to_knowledge"))
    # saved_to_knowledge 应 expires_at=NULL；即使仍带过期时间也不应被清理
    store = AttachmentStore(db)
    expired = store.expired_attachments(now=now)
    assert len(expired) == 0


def test_save_to_knowledge_clears_expires_at(db):
    kw = _db_kwargs(expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    db.create_attachment(**kw)
    store = AttachmentStore(db)
    store.mark_saved(kw["attachment_id"], "u_1", knowledge_document_id=str(uuid4()))
    row = db.get_attachment("u_1", kw["attachment_id"])
    assert row["status"] == "saved_to_knowledge"
    assert row["expires_at"] is None


# ── Store 层：所有权拒绝 ──

def test_store_get_requires_ownership(store):
    created = store.create(**_store_kwargs(user_id="u_1"))
    with pytest.raises(OwnershipError):
        store.get("u_2", created["id"])


def test_store_list_requires_thread_ownership(store):
    # thread 归属校验：fake store 里 thread 归属由 conversation 摊派，这里仅验证
    # list 方法把 user_id 透传（跨用户查不到他人 thread 的附件）
    tid = _uuid()
    store.create(**_store_kwargs(user_id="u_1", thread_id=tid))
    assert store.list_attachments("u_2", tid) == []


def test_store_delete_requires_ownership(store):
    created = store.create(**_store_kwargs(user_id="u_1"))
    with pytest.raises(OwnershipError):
        store.delete("u_2", created["id"])


def test_store_create_sets_default_expires_at(store):
    created = store.create(**_store_kwargs(user_id="u_1"))
    # 默认 expires_at = now + 7d（非空）
    assert created["expires_at"] is not None


def test_store_default_expires_about_7_days(store):
    created = store.create(**_store_kwargs(user_id="u_1"))
    exp = created["expires_at"]
    assert isinstance(exp, datetime)
    assert exp.tzinfo is not None and exp.utcoffset() == timedelta(0)
    delta = exp - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=12) < delta < timedelta(days=7, hours=12)
