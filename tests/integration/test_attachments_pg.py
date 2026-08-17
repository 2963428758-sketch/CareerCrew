"""PostgresAttachmentDb 真实建表 + AttachmentStore 行为回归测试。

缺 POSTGRES_TEST_DSN 跳过；用一次性库（guard 拒绝生产库 careercrew）。
验证：chat_attachments 表存在、迁移幂等、create/get/list/delete/expire 全链路。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from careercrew_core.conversation.attachments import (
    AttachmentStore,
    OwnershipError,
    PostgresAttachmentDb,
)

DSN = os.environ.get("POSTGRES_TEST_DSN", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set"),
]


def _require_disposable_db(dsn: str) -> None:
    dbname = urlparse(dsn.replace("postgresql://", "postgres://")).path.lstrip("/")
    if dbname == "careercrew":
        raise RuntimeError(
            "POSTGRES_TEST_DSN 指向生产库 careercrew，拒绝运行。请使用一次性测试库。"
        )


@pytest.fixture
def store_and_db():
    import psycopg

    _require_disposable_db(DSN)
    db = PostgresAttachmentDb(DSN)
    yield AttachmentStore(db), db
    with psycopg.connect(DSN) as conn, conn.transaction():
        conn.execute("DELETE FROM chat_attachments")


def test_tables_exist(store_and_db):
    _, db = store_and_db
    db._ensure()
    import psycopg

    with psycopg.connect(DSN) as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'chat_attachments'"
        ).fetchone()
        assert row is not None, "chat_attachments table missing"


def test_migration_idempotent(store_and_db):
    _, db = store_and_db
    db._ensure()
    db._ensure()


def test_create_get_delete_roundtrip(store_and_db):
    store, _ = store_and_db
    uid = "u_001"
    tid = str(uuid4())
    row = store.create(tid, uid, "报告.pdf", "u_001/t-1/x", "application/pdf", 100)
    got = store.get(uid, row["id"])
    assert got["original_filename"] == "报告.pdf"
    assert got["status"] == "uploaded"
    assert got["expires_at"] is not None
    # 跨用户拒绝
    with pytest.raises(OwnershipError):
        store.get("u_002", row["id"])
    # 删除
    assert store.delete(uid, row["id"]) is True
    with pytest.raises(OwnershipError):
        store.get(uid, row["id"])


def test_list_and_count_nondeleted(store_and_db):
    store, _ = store_and_db
    uid = "u_001"
    tid = str(uuid4())
    store.create(tid, uid, "a.pdf", "a", "application/pdf", 1)
    store.create(tid, uid, "b.pdf", "b", "application/pdf", 1)
    store.create(str(uuid4()), uid, "c.pdf", "c", "application/pdf", 1)
    assert len(store.list_attachments(uid, tid)) == 2
    assert store.count_nondeleted(uid, tid) == 2


def test_expired_and_saved_to_knowledge(store_and_db):
    store, db = store_and_db
    uid = "u_001"
    tid = str(uuid4())
    past = datetime.now(timezone.utc) - timedelta(days=1)
    exp = store.create(tid, uid, "old.pdf", "o", "application/pdf", 1,
                       expires_at=past)
    # 保存到知识库：expires_at=NULL + status=saved_to_knowledge
    db.update_status(uid, exp["id"], "uploaded")
    store.mark_saved(exp["id"], uid, knowledge_document_id=str(uuid4()))
    saved = db.get_attachment(uid, exp["id"])
    assert saved["status"] == "saved_to_knowledge"
    assert saved["expires_at"] is None
    # 已保存的不再出现在过期列表
    assert store.expired_attachments() == []
