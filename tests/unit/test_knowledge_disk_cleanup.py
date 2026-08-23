"""知识库删除的磁盘清理（delete_document 连带清原件与解析产物目录）。"""
from __future__ import annotations

import logging

from careercrew_api.runtime.knowledge import KnowledgeDocsMixin


def test_cleanup_knowledge_files(monkeypatch, tmp_path):
    """删除后原件与解析产物目录被清掉，其他文档文件不受影响；缺 owner 的条目跳过。"""
    from careercrew_api import storage
    from careercrew_api.storage import layout

    monkeypatch.setattr(storage, "L", layout(tmp_path / "data"))

    owner = "u_001"
    doc = "a1b2c3d4e5f6"
    raw_dir = storage.L.knowledge_raw / owner
    raw_dir.mkdir(parents=True)
    target_raw = raw_dir / f"{doc}.pdf"
    target_raw.write_bytes(b"pdf")
    keep_raw = raw_dir / "ffff99998888.pdf"
    keep_raw.write_bytes(b"keep")

    out_dir = storage.L.parsed_knowledge / owner / doc
    pages = out_dir / "pages"
    pages.mkdir(parents=True)
    (pages / "1.png").write_bytes(b"img")
    (out_dir / "doc.md").write_text("md", encoding="utf-8")

    KnowledgeDocsMixin._cleanup_knowledge_files([
        {"doc": doc, "owner_user_id": owner, "visibility": "private"},
        # 历史数据可能缺 owner_user_id：跳过该条且不抛错
        {"doc": "noowner12345", "visibility": "private"},
    ])

    assert not target_raw.exists()
    assert not out_dir.exists()
    assert keep_raw.is_file()


def test_cleanup_tolerates_missing_dirs(monkeypatch, tmp_path):
    """磁盘上本就无残留（如纯向量数据）时静默通过。"""
    from careercrew_api import storage
    from careercrew_api.storage import layout

    monkeypatch.setattr(storage, "L", layout(tmp_path / "data"))

    KnowledgeDocsMixin._cleanup_knowledge_files([
        {"doc": "ghost1234567", "owner_user_id": "u_404"},
    ])


def test_cleanup_failure_is_logged_and_does_not_raise(monkeypatch, tmp_path, caplog):
    """单处 IO 失败只记日志，不影响其他磁盘目标的清理。"""
    import shutil

    from careercrew_api import storage
    from careercrew_api.storage import layout

    monkeypatch.setattr(storage, "L", layout(tmp_path / "data"))

    owner = "u_001"
    doc = "a1b2c3d4e5f6"
    raw_dir = storage.L.knowledge_raw / owner
    raw_dir.mkdir(parents=True)
    raw_file = raw_dir / f"{doc}.pdf"
    raw_file.write_bytes(b"pdf")
    out_dir = storage.L.parsed_knowledge / owner / doc
    out_dir.mkdir(parents=True)

    def fail_rmtree(_path):
        raise OSError("disk busy")

    monkeypatch.setattr(shutil, "rmtree", fail_rmtree)
    with caplog.at_level(logging.ERROR):
        KnowledgeDocsMixin._cleanup_knowledge_files([
            {"doc": doc, "owner_user_id": owner},
        ])

    assert not raw_file.exists()
    assert out_dir.is_dir()
    assert "知识库解析产物清理失败" in caplog.text
