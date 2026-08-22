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

import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from careercrew_api import storage
from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.conversation.attachments import OwnershipError
from careercrew_core.conversation.validation import (
    MAX_ATTACHMENT_SIZE,
    AttachmentValidationError,
    validate_attachment,
)

router = APIRouter()

# 文本类（md/txt）快速路径：扩展名不触发 MinerU 管线，直接 MarkdownLoader 直读。
# 二进制类（pdf/docx/pptx/xlsx/png/jpg/jpeg）走 runtime.ingest_pipeline（MinerU 本地/API）。
_TEXT_EXTS = {".md", ".markdown", ".txt"}

# 允许发起 save-to-knowledge 的前置状态（failed 允许重试；ready 为契约保留的
# 过渡值——本实现不产出可观测的 ready，但历史/外部写入的 ready 行仍可直接入库）。
_SAVEABLE_STATUSES = {"uploaded", "ready", "failed"}

# 可注入的解析+入库执行函数（生产默认委托 runtime.ingest_document，测试注入 fake 断点）。
# 返回 (knowledge_document_id, doc_id)；失败抛异常由后台线程捕获写入 parser_error。
_parse_and_ingest: Callable[..., dict] | None = None

# §14.1：5 文件 / turn
_MAX_FILES_PER_TURN = 5


def _resolve_attachment_path(user_id: str, thread_id: str, attachment_id: str) -> Path:
    """在 attachments 根内构造磁盘路径（resolve_under 防目录穿越）。"""
    return storage.resolve_under(
        storage.L.attachments, user_id, thread_id, attachment_id
    )


async def _read_bounded(file: UploadFile, limit: int) -> bytes | None:
    """分块读取上传内容，最多读 limit 字节。

    通过限制读取量避免把超大上传整体缓冲进内存：读到 limit 字节后若仍有剩余
    （下一 chunk 非空）即返回 None 表示超限；否则返回完整字节内容。
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


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

    # ── 读内容（分块读，最多 MAX+1 字节；超过即拒绝，避免超大文件全读进内存）──
    content = await _read_bounded(file, MAX_ATTACHMENT_SIZE)
    if content is None:
        raise HTTPException(status_code=413, detail="附件超过 25MB 限制")

    # 文件名防路径穿越：只取 basename；原名仅进元数据。
    filename = Path(file.filename or "upload").name or "upload"
    mime = file.content_type or ""

    # ── 校验（扩展名/MIME/magic/大小，纯函数）──
    try:
        # 文本类需要全文做 UTF-8 校验，故传完整 content；二进制类签名只取头。
        meta = validate_attachment(
            filename, mime, content[:64], len(content), content=content,
        )
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
            "parser_type": r.get("parser_type"),
            "parser_error": r.get("parser_error"),
            "knowledge_document_id": r.get("knowledge_document_id"),
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


def _default_parse_and_ingest(
    rt: CareerCrewRuntime, disk_path: Path, user_id: str, filename: str,
    attachment_id: str,
) -> dict:
    """默认解析+入库：md/txt 文本直读，二进制走 MinerU 管线（复用 runtime.ingest_document）。

    knowledge 文档以附件 UUID 为 doc_id（服务端生成，稳定幂等），title=original_filename，
    owner=当前用户、visibility=private、category 自动识别（category=""）。返回
    {knowledge_document_id, doc_id, points}。
    """
    # output_dir：按用户/附件隔离的解析产物目录（与 knowledge.py 上传端点对齐）
    output_dir = storage.resolve_under(storage.L.parsed_knowledge, user_id, attachment_id)
    result = rt.ingest_document(
        str(disk_path),
        user_id=user_id,
        progress_cb=None,
        # category="" 触发自动分类：ingest_document 内部按 doc_name（原文件名）
        # 调用 category_for_doc 识别（resume/knowledge/interview），与 knowledge.py
        # 上传端点一致——chat 附件（含简历 PDF）不被硬编码成 "knowledge"。
        category="",
        output_dir=str(output_dir),
        doc_name=filename,
        visibility="private",
    )
    # ingest_document 的 doc_id 是 p.stem（=附件 UUID 文件名），即 == attachment_id
    return {
        "knowledge_document_id": attachment_id,
        "doc_id": result.get("doc_id", attachment_id),
        "points": result.get("points", 0),
    }


def _run_save_job(rt: CareerCrewRuntime, user_id: str, attachment_id: str) -> None:
    """后台线程：解析+入库并更新附件状态机（失败不阻塞、不重抛到请求方）。

    uploaded/ready/failed -> parsing（请求方已写入）-> saved_to_knowledge +
    knowledge_document_id + expires_at=NULL；任一异常 -> failed + parser_error。

    注意：ingest_document 把 parse+vectorize+store 合并为一次调用，不存在可观测的
    「解析成功、入库前」中间态，故不再写 ready（ready 仅为契约保留的过渡值，
    见下方状态机注释）。成功时显式清空 parser_error，避免上一次失败重试成功后
    残留过期错误。
    """
    try:
        row = rt.attachment_store.get(user_id, attachment_id)
    except OwnershipError:
        return
    disk_path = _resolve_attachment_path(row["user_id"], row["thread_id"], attachment_id)

    parse_fn = _parse_and_ingest or _default_parse_and_ingest
    try:
        result = parse_fn(
            rt, disk_path, user_id, row["original_filename"], attachment_id
        )
        doc_id = result.get("knowledge_document_id", attachment_id)
        # 成功路径：清除 parser_error（重试场景）并进入保存终态。
        rt.attachment_store.mark_saved(
            attachment_id, user_id, knowledge_document_id=str(doc_id)
        )
        rt.attachment_store.update_status(
            user_id, attachment_id, "saved_to_knowledge",
            parser_error=None,
            parser_type=_parser_type_for(row["original_filename"]),
            knowledge_document_id=str(doc_id),
        )
    except Exception as e:  # noqa: BLE001 - 解析/入库错误统一收口到 parser_error
        from careercrew_api.sse import friendly_error

        try:
            rt.attachment_store.update_status(
                user_id, attachment_id, "failed", parser_error=friendly_error(e),
            )
        except OwnershipError:
            pass


def _parser_type_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return "markdown" if ext in _TEXT_EXTS else "mineru"


@router.post("/{attachment_id}/save-to-knowledge", status_code=202)
def save_to_knowledge(
    attachment_id: str,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """保存附件到知识库（异步）：状态机 + 后台解析入库。

    - 所有权校验（404）；状态非 uploaded/ready/failed → 409（saved_to_knowledge 幂等拒绝）。
    - 立即置 parsing 并返回 202 {status:"parsing"}；后台线程执行解析+入库：
      成功 → saved_to_knowledge + knowledge_document_id + expires_at=NULL + 清空 parser_error；
      失败 → failed + parser_error（可重试）。
    """
    user_id = current_user["id"]
    row = _owned_attachment(rt, user_id, attachment_id)

    if row["status"] not in _SAVEABLE_STATUSES:
        detail = (
            "该附件已存入知识库" if row["status"] == "saved_to_knowledge"
            else f"附件当前状态（{row['status']}）不可保存"
        )
        raise HTTPException(status_code=409, detail=detail)

    rt.attachment_store.update_status(user_id, attachment_id, "parsing")
    threading.Thread(
        target=_run_save_job, args=(rt, user_id, attachment_id), daemon=True,
    ).start()
    return {"status": "parsing", "id": attachment_id}
