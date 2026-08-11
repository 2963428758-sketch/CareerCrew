"""MinerU loader 契约测试（mock 子进程产物 + pymupdf 渲染真实 PDF）。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from careercrew_core.rag.loaders.mineru_loader import MinerULoader, ParsingError


def _make_pdf(tmp_path: Path) -> Path:
    import pymupdf

    p = tmp_path / "resume.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "姓名：张三", fontsize=12)
    doc.save(str(p))
    doc.close()
    return p


def _fake_run_factory(auto_content: list[dict]):
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        out_root = Path(cmd[cmd.index("-o") + 1])
        stem = Path(cmd[cmd.index("-p") + 1]).stem
        auto = out_root / stem / "auto"
        (auto / "images").mkdir(parents=True, exist_ok=True)
        (auto / f"{stem}.md").write_text("# 标题\n内容", encoding="utf-8")
        (auto / f"{stem}_content_list.json").write_text(
            json.dumps(auto_content), encoding="utf-8"
        )
        (auto / "images" / "img1.jpg").write_bytes(b"\xff\xd8\xff")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    return fake_run, captured


def test_mineru_loader_parses_pages_and_objects(tmp_path, monkeypatch) -> None:
    pdf = _make_pdf(tmp_path)
    content = [
        {"type": "text", "text": "姓名：张三", "bbox": [0, 0, 100, 20], "page_idx": 0},
        {"type": "image", "text": "", "img_path": "img1.jpg", "bbox": [0, 20, 50, 50], "page_idx": 0},
    ]
    fake_run, captured = _fake_run_factory(content)
    monkeypatch.setattr(subprocess, "run", fake_run)
    parsed = MinerULoader(tmp_path / "out").parse(pdf)
    assert parsed.doc_id == "resume"
    assert len(parsed.pages) == 1
    assert parsed.pages[0].image_path.endswith(".png")
    assert "姓名：张三" in parsed.pages[0].markdown
    assert len(parsed.objects) == 1
    assert parsed.objects[0].image_path.endswith("img1.jpg")
    assert parsed.to_text() == parsed.pages[0].markdown
    assert captured["env"]["MINERU_DEVICE_MODE"] == "cpu"  # 强制 CPU，避免 8GB 显存 OOM
    assert "-m" in captured["cmd"] and captured["cmd"][captured["cmd"].index("-m") + 1] == "auto"
    assert "-f" in captured["cmd"] and captured["cmd"][captured["cmd"].index("-f") + 1] == "true"


def test_mineru_loader_passes_fast_args(tmp_path, monkeypatch) -> None:
    pdf = _make_pdf(tmp_path)
    fake_run, captured = _fake_run_factory([])
    monkeypatch.setattr(subprocess, "run", fake_run)
    MinerULoader(tmp_path / "out", method="txt", formula=False).parse(pdf)
    assert captured["cmd"][captured["cmd"].index("-m") + 1] == "txt"
    assert captured["cmd"][captured["cmd"].index("-f") + 1] == "false"


def test_mineru_loader_error_raises(tmp_path, monkeypatch) -> None:
    pdf = _make_pdf(tmp_path)

    def failing_run(cmd, **kwargs):
        class R:
            returncode = 1
            stdout = ""
            stderr = "boom"

        return R()

    monkeypatch.setattr(subprocess, "run", failing_run)
    with pytest.raises(ParsingError):
        MinerULoader(tmp_path / "out").parse(pdf)
