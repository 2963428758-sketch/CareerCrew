import importlib
from uuid import UUID

import pytest

from tests.preparation_fakes import SqlitePreparationPool


@pytest.fixture
def store():
    try:
        module = importlib.import_module("careercrew_core.preparation.store")
    except ModuleNotFoundError:
        yield None
        return
    pool = SqlitePreparationPool()
    yield module.PreparationStore(pool=pool)
    pool.close()


JOB = {"company": "测试公司", "title": "Java工程师", "jd": "开发接口"}
VERSION = {"label": "接口开发版", "content": "参与接口开发", "original_content": "原始简历"}


def test_owner_isolation_and_parameterized_crud(store):
    assert store is not None, "岗位准备持久化尚未实现"
    alice = "alice' OR 1=1 --"
    row = store.create_opportunity(alice, JOB)
    assert row["company"] == "测试公司"
    assert row["city"] == ""
    assert "owner_id" not in row
    assert store.get_opportunity("bob", row["id"]) is None
    assert store.list_opportunities("bob") == []
    assert store.update_opportunity("bob", row["id"], JOB) is None
    assert not store.delete_opportunity("bob", row["id"])
    updated = store.update_opportunity(alice, row["id"], {**JOB, "title": "后端工程师"})
    assert updated["title"] == "后端工程师"
    assert store.list_opportunities(alice)[0]["id"] == row["id"]


def test_versions_append_and_session_snapshots_do_not_follow_edits(store):
    assert store is not None, "岗位准备持久化尚未实现"
    job = store.create_opportunity("alice", JOB)
    first = store.create_version("alice", job["id"], VERSION)
    second = store.create_version("alice", job["id"], {**VERSION, "content": "改进简历"})
    assert first["id"] != second["id"]
    assert store.get_version("alice", job["id"], first["id"])["content"] == "参与接口开发"
    assert len(store.list_versions("alice", job["id"])) == 2
    for module, prefix in [("resume", "r-prep-"), ("interview", "i-prep-")]:
        session = store.create_session("alice", job["id"], {
            "module": module, "resume_version_id": first["id"]})
        assert session["thread_id"].startswith(prefix)
        UUID(session["thread_id"][len(prefix):])
        store.update_opportunity("alice", job["id"], {**JOB, "jd": "修改后的职责"})
        saved = store.get_session("alice", session["thread_id"])
        assert saved["resume_content"] == "参与接口开发"
        assert saved["resume_label"] == "接口开发版"
        assert saved["jd"] == ("开发接口" if module == "resume" else "修改后的职责")
        assert store.get_session("bob", session["thread_id"]) is None


def test_cross_owner_and_cross_opportunity_versions_cannot_be_used(store):
    assert store is not None, "岗位准备持久化尚未实现"
    job = store.create_opportunity("alice", JOB)
    other = store.create_opportunity("alice", JOB)
    version = store.create_version("alice", job["id"], VERSION)
    assert store.create_version("bob", job["id"], VERSION) is None
    assert store.list_versions("bob", job["id"]) == []
    assert store.get_version("bob", job["id"], version["id"]) is None
    assert store.get_version("alice", other["id"], version["id"]) is None
    for owner, oid in [("bob", job["id"]), ("alice", other["id"])]:
        assert store.create_session(owner, oid, {
            "module": "resume", "resume_version_id": version["id"]}) is None


def test_deletion_cascades_and_account_cleanup_preserves_other_owner(store):
    assert store is not None, "岗位准备持久化尚未实现"
    job = store.create_opportunity("alice", JOB)
    version = store.create_version("alice", job["id"], VERSION)
    session = store.create_session("alice", job["id"], {
        "module": "interview", "resume_version_id": version["id"]})
    bob = store.create_opportunity("bob", JOB)
    assert store.delete_opportunity("alice", job["id"])
    assert store.get_version("alice", job["id"], version["id"]) is None
    assert store.get_session("alice", session["thread_id"]) is None
    store.create_opportunity("alice", JOB)
    store.delete_all_for_user("alice")
    assert store.list_opportunities("alice") == []
    assert store.get_opportunity("bob", bob["id"])["company"] == "测试公司"
