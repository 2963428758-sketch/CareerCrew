"""Two independent workers; only a newly created disposable PostgreSQL DB is written."""
from __future__ import annotations

import os
import runpy
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

import pytest

from careercrew_core.knowledge.governance import KnowledgeGovernance
from careercrew_core.memory.db import PostgresMemoryDb

pytestmark = [pytest.mark.integration]


@pytest.fixture
def workers(valid_config_data):
    import psycopg
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from sqlalchemy import create_engine

    from careercrew_ai.vector_store.qdrant_store import QdrantStore
    from careercrew_core.state.settings import Settings

    dsn = os.environ.get("POSTGRES_TEST_DSN")
    if not dsn:
        pytest.skip("POSTGRES_TEST_DSN not set (needs CREATE DATABASE)")
    params = conninfo_to_dict(dsn)
    if params.get("host") not in {"127.0.0.1", "localhost"}:
        pytest.fail("Concurrency test only permits local PostgreSQL")
    name = "cc_governance_test_" + uuid.uuid4().hex
    admin_dsn = make_conninfo(dsn, dbname="postgres")
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    test_dsn = make_conninfo(dsn, dbname=name)
    try:
        engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(test_dsn))
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                for file in ("0010_knowledge_governance.py", "0017_knowledge_source_identity.py"):
                    runpy.run_path(str(Path(__file__).parents[2] / "migrations/versions" / file))["upgrade"]()
        engine.dispose()
        dbs = [PostgresMemoryDb(test_dsn), PostgresMemoryDb(test_dsn)]
        for db in dbs:
            db._schema_ready = True  # this test needs only the actual governance migrations
        store = QdrantStore(Settings.model_validate(valid_config_data))
        yield [KnowledgeGovernance(db, vector_store=store) for db in dbs], store
    finally:
        from careercrew_core.pg_pool import get_shared_pool
        get_shared_pool(test_dsn).close()
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _indexer(store, created, visibility, entered=None, release=None):
    from careercrew_ai.vector_store.base_vector_store import VectorRecord

    def index(chunk):
        if entered is not None:
            entered.set()
            assert release.wait(10), "worker was not released"
        point = f"governance:{created['document_id']}:{created['version_id']}:{chunk['id']}"
        store.upsert([VectorRecord(id=point, dense=[0.1] * 1024, text=chunk["text"], metadata={
            "doc": "governance:" + created["document_id"], "owner_user_id": "u1",
            "visibility": visibility, "record_type": "knowledge_governance",
            "governance_document_id": created["document_id"],
            "governance_version_id": created["version_id"],
            "governance_chunk_id": chunk["id"], "governance_status": "indexing",
        })])
        return point
    return index


def _create(service):
    return service.create_document("u1", name="concurrent", content_sha256="a" * 64,
        size_bytes=1, visibility="public", is_admin=True, chunks=[{"text": "original"}])


def _assert_database_waiter(service):
    """Prove blocking is a PostgreSQL lock, rather than worker scheduling delay."""
    import psycopg

    deadline = time.monotonic() + 5
    with psycopg.connect(service.db._dsn, autocommit=True) as conn:
        while time.monotonic() < deadline:
            row = conn.execute("SELECT count(*) FROM pg_stat_activity "
                "WHERE datname=current_database() AND wait_event_type='Lock'").fetchone()
            if row[0]:
                return
            time.sleep(0.02)
    pytest.fail("second worker never waited on a PostgreSQL lock")


def test_activation_uses_current_visibility_not_indexer_snapshot(workers):
    (first, second), store = workers
    created = _create(first)
    stale_indexer = _indexer(store, created, "public")
    second.unpublish_document("u1", created["document_id"])
    first.reindex("u1", created["document_id"], created["version_id"], indexer=stale_indexer)
    assert not store.list_docs(filters={"__access_user": "other", "__governance_active": True})


@pytest.mark.parametrize("target", ["private", "public"])
def test_visibility_commit_failure_reconciles_vectors_with_database(workers, target):
    import psycopg

    (first, _), store = workers
    created = _create(first)
    first.reindex("u1", created["document_id"], created["version_id"],
        indexer=_indexer(store, created, "public"))
    if target == "public":
        first.unpublish_document("u1", created["document_id"])
    initial = "private" if target == "public" else "public"
    # A real deferred trigger fails COMMIT after the vector write succeeded.
    with first.db._borrow() as conn:
        conn.execute("""CREATE FUNCTION reject_visibility_commit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected commit failure'; END $$""")
        conn.execute("""CREATE CONSTRAINT TRIGGER reject_visibility_commit AFTER UPDATE
            ON knowledge_documents DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION reject_visibility_commit()""")
    operation = first.publish_document if target == "public" else first.unpublish_document
    with pytest.raises(psycopg.Error):
        operation("u1", created["document_id"])
    assert first.get_document("u1", created["document_id"])["visibility"] == initial
    docs = store.list_docs(filters={"doc": "governance:" + created["document_id"]})
    assert docs[0]["visibility"] == initial


def test_reindex_commit_failure_keeps_previous_projection(workers):
    import psycopg

    (first, _), store = workers
    created = _create(first)
    first.reindex("u1", created["document_id"], created["version_id"],
        indexer=_indexer(store, created, "public"))
    newer = first.create_version("u1", created["document_id"], content_sha256="b" * 64,
        size_bytes=2, chunks=[{"text": "new version"}])
    with first.db._borrow() as conn:
        conn.execute("""CREATE FUNCTION reject_activation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected commit failure'; END $$""")
        conn.execute("""CREATE CONSTRAINT TRIGGER reject_activation AFTER UPDATE
            ON knowledge_documents DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION reject_activation()""")
    with pytest.raises(psycopg.Error):
        first.reindex("u1", created["document_id"], newer["version_id"],
            indexer=_indexer(store, newer, "public"))
    assert first.get_document("u1", created["document_id"])["active_version_id"] == created["version_id"]
    assert store.metadata_exists({"governance_version_id": created["version_id"], "governance_status": "active"})
    assert not store.metadata_exists({"governance_version_id": newer["version_id"], "governance_status": "active"})


def test_stale_recovery_does_not_delete_a_new_workers_projection(workers, monkeypatch):
    (first, second), store = workers
    created = _create(first)
    with first.db._borrow() as conn:
        conn.execute("UPDATE knowledge_document_versions SET status='indexing',"
            "updated_at=now()-interval '2 hours' WHERE id=%s", (created["version_id"],))
    entered, release = threading.Event(), threading.Event()
    original = store.delete_by_metadata

    def delayed_delete(filters):
        entered.set()
        assert release.wait(10)
        return original(filters)

    monkeypatch.setattr(store, "delete_by_metadata", delayed_delete)
    with ThreadPoolExecutor(max_workers=2) as pool:
        recovery = pool.submit(first.recover_stale_indexing, "u1")
        assert entered.wait(10)
        indexing = pool.submit(second.reindex, "u1", created["document_id"], created["version_id"],
            indexer=_indexer(store, created, "public"))
        try:
            _assert_database_waiter(first)
            with pytest.raises(TimeoutError):
                indexing.result(timeout=0.4)
        finally:
            release.set()
        recovery.result(timeout=10)
        indexing.result(timeout=10)
    assert store.metadata_exists({"governance_version_id": created["version_id"], "governance_status": "active"})


@pytest.mark.parametrize("mutation", ["unpublish", "publish", "edit", "reindex"])
def test_second_worker_cannot_mutate_between_index_write_and_activation(workers, mutation):
    (first, second), store = workers
    created = _create(first)
    first.reindex("u1", created["document_id"], created["version_id"],
        indexer=_indexer(store, created, "public"))
    if mutation == "publish":
        first.unpublish_document("u1", created["document_id"])
    chunk_id = first.get_document("u1", created["document_id"])["versions"][0]["chunks"][0]["id"]
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()

    def mutate():
        attempted.set()
        if mutation == "unpublish":
            return second.unpublish_document("u1", created["document_id"])
        if mutation == "publish":
            return second.publish_document("u1", created["document_id"])
        if mutation == "reindex":
            return second.reindex("u1", created["document_id"], created["version_id"],
                indexer=_indexer(store, created, "public"))
        return second.update_chunk("u1", created["document_id"], created["version_id"], chunk_id,
            text="edited after indexing")

    with ThreadPoolExecutor(max_workers=2) as pool:
        indexing = pool.submit(first.reindex, "u1", created["document_id"], created["version_id"],
            indexer=_indexer(store, created, "public", entered, release))
        assert entered.wait(10)
        changing = pool.submit(mutate)
        try:
            assert attempted.wait(10)
            _assert_database_waiter(first)
            with pytest.raises(TimeoutError):
                changing.result(timeout=0.4)
        finally:
            release.set()
        indexing.result(timeout=10)
        changing.result(timeout=10)
    detail = first.get_document("u1", created["document_id"])
    if mutation == "edit":
        assert detail["active_version_id"] is None
        assert detail["versions"][0]["chunks"][0]["text"] == "edited after indexing"
        assert detail["versions"][0]["chunks"][0]["index_status"] == "pending"
    elif mutation == "unpublish":
        assert detail["visibility"] == "private"
    public_docs = store.list_docs(filters={"__access_user": "other", "__governance_active": True})
    assert bool(public_docs) == (mutation in {"publish", "reindex"})


def test_indexer_failure_rolls_back_cutover_and_preserves_old_version(workers):
    (first, _), store = workers
    created = _create(first)
    first.reindex("u1", created["document_id"], created["version_id"],
        indexer=_indexer(store, created, "public"))
    newer = first.create_version("u1", created["document_id"], content_sha256="b" * 64,
        size_bytes=2, chunks=[{"text": "new version"}])
    write = _indexer(store, newer, "public")

    def broken(chunk):
        write(chunk)
        raise RuntimeError("worker failed after writing a point")

    with pytest.raises(RuntimeError, match="worker failed"):
        first.reindex("u1", created["document_id"], newer["version_id"], indexer=broken)
    detail = first.get_document("u1", created["document_id"])
    assert detail["active_version_id"] == created["version_id"]
    assert detail["versions"][0]["status"] == "failed"
    assert store.metadata_exists({"governance_version_id": created["version_id"], "governance_status": "active"})
    assert not store.metadata_exists({"governance_version_id": newer["version_id"], "governance_status": "active"})
