"""上传与解析存储布局 + 根目录受限路径校验（Task 2：上传隔离、UUID 与路径安全）。

布局（新文件一律 UUID 键名，原文件名只进元数据）：

    data/uploads/resumes_raw/{user_id}/{uuid}.{ext}     简历原件
    data/uploads/knowledge_raw/{user_id}/{uuid}.{ext}   知识库原件
    data/uploads/attachments/{user_id}/{thread_id}/{attachment_uuid}  会话附件
    data/uploads/resume_threads/{user_id}/{sha256}.txt  对话式简历线程存储
    data/parsed/resumes/{user_id}/{uuid}/               简历解析产物（content.txt + meta.json）
    data/parsed/knowledge/{user_id}/{document_uuid}/    知识库解析产物（MinerU）

任何从磁盘路径读写文件的地方都必须先经 ``resolve_under`` 校验根目录归属。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


def layout(data_root: Path) -> SimpleNamespace:
    """按给定数据根构造目录布局（测试可注入 tmp 根）。"""
    up = Path(data_root) / "uploads"
    parsed = Path(data_root) / "parsed"
    return SimpleNamespace(
        uploads=up,
        resumes_raw=up / "resumes_raw",
        knowledge_raw=up / "knowledge_raw",
        attachments=up / "attachments",
        resume_threads=up / "resume_threads",
        parsed_resumes=parsed / "resumes",
        parsed_knowledge=parsed / "knowledge",
    )


L = layout(DATA_ROOT)


def resolve_under(root: Path, *parts: str) -> Path:
    """在 root 内按 parts 拼接并 resolve；路径越出 root 时抛 ValueError（防目录穿越）。"""
    resolved_root = Path(root).resolve()
    p = resolved_root.joinpath(*[Path(part) for part in parts]).resolve()
    if not p.is_relative_to(resolved_root):
        raise ValueError(f"路径越界: {p} 不在 {resolved_root} 内")
    return p


def is_within_data(p: Path) -> bool:
    """路径 resolve 后是否仍落在 data 根目录内。"""
    try:
        p.resolve().relative_to(DATA_ROOT.resolve())
        return True
    except ValueError:
        return False
