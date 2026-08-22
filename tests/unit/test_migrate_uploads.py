"""审计/迁移脚本单元测试（tmp 目录，不触碰真实 data/uploads）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from careercrew_api.storage import layout
from scripts.audit_uploads import audit
from scripts.migrate_uploads import plan_moves


@pytest.fixture
def legacy_tree(tmp_path):
    up = tmp_path / "data" / "uploads"
    (up / "u_001").mkdir(parents=True)
    (up / "u_001" / "简历.pdf").write_text("pdf", encoding="utf-8")
    (up / "note.md").write_text("md", encoding="utf-8")
    (up / "resumes").mkdir()
    (up / "resumes" / "old.docx").write_text("docx", encoding="utf-8")
    return up


def test_audit_classifies_kinds(legacy_tree, tmp_path):
    lay = layout(tmp_path / "data")
    rows = audit(legacy_tree, lay=lay)
    kinds = {Path(r["path"]).name: r["kind"] for r in rows}
    assert kinds["简历.pdf"] == "resume"
    assert kinds["note.md"] == "knowledge"
    assert kinds["old.docx"] == "resume"  # resumes/ 子目录 → resume
    assert all(r["owner"] == "u_001" for r in rows if Path(r["path"]).name == "note.md")


def test_audit_skips_new_layout(tmp_path):
    lay = layout(tmp_path / "data")
    raw = lay.knowledge_raw / "u_001"
    raw.mkdir(parents=True)
    (raw / "abc123.pdf").write_text("x", encoding="utf-8")
    rows = audit(lay.uploads, lay=lay)
    assert rows == []


def test_plan_moves_targets_inside_layout(legacy_tree, tmp_path):
    lay = layout(tmp_path / "data")
    rows = audit(legacy_tree, lay=lay)
    moves = plan_moves(rows, lay=lay)
    assert len(moves) == 3
    for _src, target in moves:
        assert target.is_relative_to(lay.uploads)
        assert "简历" not in target.name  # UUID 键名，不含原名


def test_apply_moves_files(legacy_tree, tmp_path):
    import shutil

    from scripts.migrate_uploads import plan_moves

    lay = layout(tmp_path / "data")
    rows = audit(legacy_tree, lay=lay)
    for src, target in plan_moves(rows, lay=lay):
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
    assert not (legacy_tree / "u_001" / "简历.pdf").exists()
    assert (lay.resumes_raw / "u_001").exists()


def test_malicious_name_normalized(tmp_path):
    """文件名含 ../ 时审计归一为 basename（路径不逃逸）。"""
    up = tmp_path / "data" / "uploads" / "u_001"
    up.mkdir(parents=True)
    (up / "safe.pdf").write_text("x", encoding="utf-8")
    lay = layout(tmp_path / "data")
    rows = audit(up, lay=lay)
    assert len(rows) == 1
    assert Path(rows[0]["path"]).name == "safe.pdf"
