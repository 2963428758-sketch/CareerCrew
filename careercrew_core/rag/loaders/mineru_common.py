"""MinerU 解析产物组装公共逻辑（本地子进程 / 云端 API 共用，R6）。

两种 loader 产出的目录结构一致：
- ``<stem>.md`` + ``<stem>_content_list.json``：页面文本 / 对象块
- ``images/``：MinerU 裁剪图（对象块）
- ``pages/page_NNN.png``：pymupdf 渲染的整页图（VLM 看图回答展示用）

这里只负责「产物 -> ParsedDocument」，不做任何推理 / 网络 IO。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from careercrew_core.rag.loaders.base_loader import (
    ParsedDocument,
    ParsedObject,
    ParsedPage,
)


class ParsingError(RuntimeError):
    """文档解析失败（MinerU 子进程非零退出 / API 失败 / 产物缺失）。"""


def sanitize_doc_id(name: str) -> str:
    """文件名 -> 安全 doc_id（与旧 Milvus 命名规则一致，幂等 id 基础）。"""
    return re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name).strip("._") or "doc"


def render_pages(src: Path, out_root: Path) -> list[ParsedPage]:
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


def load_content_items(content_path: Path | None) -> list[dict]:
    """读取 MinerU ``*_content_list.json``（扁平列表；dict 包装则取常见键）。"""
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


def build_parsed_document(
    doc_id: str,
    src: Path,
    out_root: Path,
    content_root: Path,
) -> ParsedDocument:
    """把 MinerU 产物目录组装为 ParsedDocument。

    ``content_root`` 是含 ``*.md`` / ``*_content_list.json`` / ``images/`` 的目录
    （本地 loader 为 ``out_root/<stem>/auto``，API loader 为 zip 解压目录）。
    ``out_root`` 用于放置 pymupdf 渲染的整页图（``out_root/pages/``）。
    """
    md_path = next(content_root.glob("*.md"), None)
    content_path = next(content_root.glob("*_content_list.json"), None)
    images_dir = content_root / "images"

    pages = render_pages(src, out_root)
    items = load_content_items(content_path)
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
