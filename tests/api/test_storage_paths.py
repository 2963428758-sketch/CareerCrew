"""storage 路径校验单元测试：越界、绝对路径、UUID 布局。"""
from __future__ import annotations

import pytest

from careercrew_api.storage import L, resolve_under


def test_resolve_under_normal():
    p = resolve_under(L.resumes_raw, "u_001", "abc.pdf")
    assert p.parent == L.resumes_raw / "u_001"
    assert p.name == "abc.pdf"


def test_resolve_under_rejects_traversal():
    with pytest.raises(ValueError):
        resolve_under(L.resumes_raw, "u_001", "../../etc/passwd")
    with pytest.raises(ValueError):
        resolve_under(L.resumes_raw, "..", "x.pdf")  # 从根目录直接越界


def test_resolve_under_rejects_absolute(tmp_path):
    outside = tmp_path / "outside.txt"  # 平台无关的绝对路径（Windows/Linux 均有效）
    with pytest.raises(ValueError):
        resolve_under(L.resumes_raw, str(outside))


def test_distinct_uploads_distinct_paths():
    a = resolve_under(L.resumes_raw, "u_001", "uuid-1.pdf")
    b = resolve_under(L.resumes_raw, "u_001", "uuid-2.pdf")
    assert a != b


def test_layout_has_required_dirs(tmp_path):
    from careercrew_api.storage import layout

    lay = layout(tmp_path / "data")
    assert lay.resumes_raw == tmp_path / "data" / "uploads" / "resumes_raw"
    assert lay.knowledge_raw == tmp_path / "data" / "uploads" / "knowledge_raw"
    assert lay.parsed_resumes == tmp_path / "data" / "parsed" / "resumes"
    assert lay.parsed_knowledge == tmp_path / "data" / "parsed" / "knowledge"
