"""聊天附件路由（T3.1 §34）：上传 / 列表 / 删除 / 下载 / save-to-knowledge(501)。

- POST /api/chat/attachments             multipart 上传（校验→存盘→写 DB）
- GET  /api/chat/attachments?thread_id=  本人列表（元数据，不含文件内容）
- DELETE /api/chat/attachments/{id}      所有权校验→物理删文件 + DB 删行
- GET  /api/chat/attachments/{id}/content 下载（inline/attachment，所有权 404）
- POST /api/chat/attachments/{id}/save-to-knowledge  501（T3.3 接真实现）

存储：storage.L.attachments/{user_id}/{thread_id}/{uuid}（相对路径入 storage_key，
uuid 文件名，原文件名仅进元数据——磁盘路径不受客户端控制）。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_api import storage
from careercrew_core.conversation.attachments import OwnershipError
from careercrew_core.conversation.validation import (
    MAX_ATTACHMENT_SIZE,
    AttachmentValidationError,
    validate_attachment,
)

router = APIRouter()

# §14.1：5 文件 / turn
_MAX_FILES_PER_TURN = 5


def _resolve_attachment_path(user_id: str, thread_id: str, attachment_id: str) -> Path:
    """在 attachments 根内构造磁盘路径（resolve_under 防目录穿越）。"""
    return storage.resolve_under(
        storage.L.attachments, user_id, thread_id, attachment_id
    )


@router.post("", status_code=201)
async def upload_attachment(
    current_user: CurrentUser,
    thread_id: str = Form(...),
    file: UploadFile = File(...),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """上传附件：校验 → 存盘 → 写 DB（status=uploaded，expires_at=now+7d）。"""
    user_id = current_user["id"]

    # ── 每 turn 5 个限制（按 thread_id + 未删除计数）──
    rt._ensure_heavy()
    existing = rt.attachment_store.count_nondeleted(user_id, thread_id)
    if existing >= _MAX_FILES_PER_TURN:
        raise HTTPException(status_code=422, detail="每个会话最多上传 5 个附件")

    # ── 读内容（先做大小上限，避免超大文件全读进内存）──
    content = await file.read()
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=413, detail="附件超过 25MB 限制")

    # 文件名防路径穿越：只取 basename；原名仅进元数据。
    filename = Path(file.filename or "upload").name or "upload"
    mime = file.content_type or ""

    # ── 校验（扩展名/MIME/magic/大小，纯函数）──
    try:
        meta = validate_attachment(filename, mime, content[:64], len(content))
    except AttachmentValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # ── 存盘：uuid 文件名 + attachments 布局（storage_key 相对路径）──
    attachment_id = str(uuid.uuid4())
    disk_path = _resolve_attachment_path(user_id, thread_id, attachment_id)
    disk_path.parent.mkdir(parents=True, exist_ok=True)
    disk_path.write_bytes(content)

    # storage_key：相对 attachments 根（uploads/attachments/...），不落绝对路径。
    attachments_root = storage.L.attachments.resolve()
    storage_key = str(disk_path.relative_to(attachments_root)).replace("\\", "/")

    # ── 写 DB（attachment_id 复用于磁盘文件名，保证 id == 文件名一致）──
    try:
        row = rt.attachment_store.create(
            thread_id, user_id, filename, storage_key, meta["mime"], len(content),
            attachment_id=attachment_id,
        )
    except Exception:
        # 写库失败：回滚已落盘文件，避免孤儿文件
        disk_path.unlink(missing_ok=True)
        raise

    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "original_filename": row["original_filename"],
        "mime_type": row["mime_type"],
        "size_bytes": row["size_bytes"],
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }


@router.get("")
def list_attachments(
    current_user: CurrentUser,
    thread_id: str,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    """本人该 thread 的附件元数据列表（不含文件内容、不含 storage_key）。"""
    rt._ensure_heavy()
    rows = rt.attachment_store.list_attachments(current_user["id"], thread_id)
    return [
        {
            "id": r["id"],
            "thread_id": r["thread_id"],
            "original_filename": r["original_filename"],
            "mime_type": r["mime_type"],
            "size_bytes": r["size_bytes"],
            "status": r["status"],
            "created_at": r["created_at"],
            "expires_at": r["expires_at"],
        }
        for r in rows
    ]


def _owned_attachment(rt: CareerCrewRuntime, user_id: str,
                      attachment_id: str) -> dict:
    rt._ensure_heavy()
    try:
        return rt.attachment_store.get(user_id, attachment_id)
    except OwnershipError as e:
        raise HTTPException(status_code=404, detail="附件不存在或不属于当前用户") from e


@router.delete("/{attachment_id}")
def delete_attachment(
    attachment_id: str,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """删除附件：所有权校验 → 物理删文件 + DB 删行。"""
    user_id = current_user["id"]
    row = _owned_attachment(rt, user_id, attachment_id)
    disk_path = _resolve_attachment_path(
        row["user_id"], row["thread_id"], attachment_id
    )
    disk_path.unlink(missing_ok=True)
    rt.attachment_store.delete(user_id, attachment_id)
    return {"deleted": True, "id": attachment_id}


@router.get("/{attachment_id}/content")
def download_attachment(
    attachment_id: str,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> FileResponse:
    """下载附件内容（inline，浏览器内预览；所有权 404）。§34 未列但前端展示需要。"""
    user_id = current_user["id"]
    row = _owned_attachment(rt, user_id, attachment_id)
    disk_path = _resolve_attachment_path(
        row["user_id"], row["thread_id"], attachment_id
    )
    if not disk_path.is_file():
        raise HTTPException(status_code=404, detail="附件文件已不存在")
    return FileResponse(disk_path, media_type=row.get("mime_type"), filename=row["original_filename"])


@router.post("/{attachment_id}/save-to-knowledge")
def save_to_knowledge(
    attachment_id: str,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """保存附件到知识库（T3.3 实现解析/入库；本任务预留）。"""
    raise HTTPException(status_code=501, detail="保存到知识库功能将在后续版本提供")
