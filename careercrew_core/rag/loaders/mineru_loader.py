"""MinerU 多模态解析 loader（R2/R6）。

以独立子进程跑 `mineru -b pipeline`（模型不占本进程显存），
产物落盘到 ``output_dir/<doc_id>/``：
- ``<stem>.md`` + ``<stem>_content_list.json``：页面文本 / 对象块
- ``images/``：MinerU 裁剪图（对象块）
- ``pages/page_NNN.png``：pymupdf 渲染的整页图（ColPali 视觉路用）

解析失败抛 ``ParsingError``（调用方记 doc_type=error 跳过，不中断批量入库）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from careercrew_core.rag.loaders.base_loader import (
    ParsedDocument,
    ParsedObject,
    ParsedPage,
)

_TEXT_EXTS = {".md", ".markdown", ".txt"}


class ParsingError(RuntimeError):
    """文档解析失败（MinerU 子进程非零退出 / 产物缺失）。"""


class MinerULoader:
    """MinerU 子进程解析：PDF/图片/docx/pptx/xlsx -> 页面 + 对象。"""

    def __init__(self, output_dir: str | Path) -> None:
        self._output_dir = Path(output_dir)
        self._exe = self._find_exe()

    @staticmethod
    def _find_exe() -> str:
        """优先用当前 Python 环境的 Scripts/mineru(.exe)，回退 PATH。"""
        env_root = Path(sys.executable).parent
        scripts = env_root / "Scripts"
        for name in ("mineru.exe", "mineru"):
            for base in (scripts, env_root):
                p = base / name
                if p.exists():
                    return str(p)
        return "mineru"

    @staticmethod
    def _sanitize(name: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name).strip("._") or "doc"

    def parse(self, path: str | Path) -> ParsedDocument:
        src = Path(path)
        doc_id = self._sanitize(src.stem)
        out_root = self._output_dir / doc_id
        out_root.mkdir(parents=True, exist_ok=True)

        try:
            proc = subprocess.run(
                [
                    self._exe, "-p", str(src), "-o", str(out_root),
                    "-b", "pipeline", "-m", "auto", "-l", "ch",
                ],
                capture_output=True, text=True, timeout=900,
                encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired as e:
            raise ParsingError(f"MinerU 解析超时: {src}") from e
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-500:]
            raise ParsingError(f"MinerU 解析失败 ({src}): {tail}")

        # MinerU 产物位于 out_root/<stem>/auto/
        auto_dir = out_root / doc_id / "auto"
        if not auto_dir.exists():
            cands = [p for p in out_root.rglob("auto") if p.is_dir()]
            auto_dir = cands[0] if cands else out_root

        md_path = next(auto_dir.glob("*.md"), None)
        content_path = next(auto_dir.glob("*_content_list.json"), None)
        images_dir = auto_dir / "images"

        pages = self._render_pages(src, out_root)
        items = self._load_content_items(content_path)
        page_texts: dict[int, list[str]] = {}
        objects: list[ParsedObject] = []
        if items:
            for it in items:
                page_idx = it.get("page_idx", 0) or 0
                if it.get("type") == "image":
                    img = it.get("img_path") or ""
                    img_path = str(images_dir / img) if img else ""
                    objects.append(
                        ParsedObject(
                            page_no=page_idx + 1,
                            image_path=img_path,
                            text=it.get("text") or "",
                            bbox=it.get("bbox"),
                        )
                    )
                else:
                    text = (it.get("text") or "").strip()
                    if text:
                        page_texts.setdefault(page_idx, []).append(text)
        else:
            # 无 content_list：整文 md 归到第 1 页
            if md_path:
                page_texts.setdefault(0, []).append(md_path.read_text(encoding="utf-8"))

        for page in pages:
            text = "\n".join(page_texts.get(page.page_no - 1, []))
            if not text and md_path and len(pages) == 1:
                text = md_path.read_text(encoding="utf-8")
            page.markdown = text

        return ParsedDocument(
            doc_id=doc_id,
            pages=pages,
            objects=objects,
            metadata={"source_path": str(src), "doc_type": src.suffix.lstrip(".") or "unknown"},
        )

    def _render_pages(self, src: Path, out_root: Path) -> list[ParsedPage]:
        """pymupdf 渲染整页 PNG（保留给 VLM 看图回答展示）。"""
        import pymupdf

        pages_dir = out_root / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        rendered: list[ParsedPage] = []
        try:
            doc = pymupdf.open(str(src))
        except Exception as e:
            raise ParsingError(f"页面渲染失败 ({src}): {e}") from e
        try:
            for i, page in enumerate(doc):
                img_path = pages_dir / f"page_{i + 1:03d}.png"
                if not img_path.exists():
                    pix = page.get_pixmap(dpi=144)
                    pix.save(str(img_path))
                rendered.append(ParsedPage(page_no=i + 1, image_path=str(img_path), markdown=""))
        finally:
            doc.close()
        return rendered

    @staticmethod
    def _load_content_items(content_path: Path | None) -> list[dict]:
        if content_path is None or not content_path.exists():
            return []
        try:
            data = json.loads(content_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("content_list", "items", "blocks"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []
