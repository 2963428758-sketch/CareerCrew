from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from careercrew_core.conversation.db import FakeConversationDb
from careercrew_core.conversation.store import ConversationStore
from careercrew_core.workspace.resume import ResumeWorkspace


def test_resume_master_derived_diff_annotations_and_batch_export() -> None:
    workspace = ResumeWorkspace(ConversationStore(FakeConversationDb()))
    master = workspace.create_master("alice", title="通用母版", content="Java 工程师\n负责 API")
    base = workspace.list_versions("alice", master["id"])[0]
    derived = workspace.create_version(
        "alice", master["id"], label="AI 岗位版", content="Java 工程师\n负责 RAG API",
        parent_version_id=base["id"], kind="derived",
    )
    diff = workspace.diff_versions("alice", base["id"], derived["id"])
    assert diff["changed"] is True
    assert "RAG" in diff["unified_diff"]

    material = workspace.create_material(
        "alice", title="RAG 项目", context="检索", role="负责人",
        actions="搭建重排", results="Recall +20%", tags=["RAG"],
    )
    assert material["results"] == "Recall +20%"
    annotation = workspace.create_annotation(
        "alice", derived["id"], start_offset=0, end_offset=3, note="确认职位名称"
    )
    assert workspace.list_annotations("alice", derived["id"])[0]["id"] == annotation["id"]

    job = workspace.create_export_job("alice", [base["id"], derived["id"]], ["pdf", "docx"])
    assert job["status"] == "queued"
    done = workspace.run_export_job("alice", job["id"])
    assert done["status"] == "done"
    payload = workspace.download_export("alice", job["id"])
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        assert len(archive.namelist()) == 4


def test_resume_workspace_never_returns_foreign_versions() -> None:
    workspace = ResumeWorkspace(ConversationStore(FakeConversationDb()))
    master = workspace.create_master("alice", title="Alice", content="secret resume")
    version = workspace.list_versions("alice", master["id"])[0]
    assert workspace.list_masters("bob") == []
    assert workspace.diff_versions("bob", version["id"], version["id"]) is None
    try:
        workspace.create_annotation("bob", version["id"], start_offset=0, end_offset=1, note="leak")
    except PermissionError:
        pass
    else:
        raise AssertionError("foreign resume version must be hidden")


def test_resume_export_failure_does_not_expose_raw_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from careercrew_core.workspace import resume as resume_module

    workspace = ResumeWorkspace(ConversationStore(FakeConversationDb()))
    master = workspace.create_master("alice", title="Alice", content="resume")
    version = workspace.list_versions("alice", master["id"])[0]
    job = workspace.create_export_job("alice", [version["id"]], ["pdf"])
    monkeypatch.setattr(
        resume_module,
        "export_pdf",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("password=secret C:\\private\\resume")),
    )
    failed = workspace.run_export_job("alice", job["id"])

    assert failed["status"] == "failed"
    assert "secret" not in str(failed["error"])
    assert "private" not in str(failed["error"])
