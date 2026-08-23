"""知识库路由：异步上传入库（任务 + 进度查询）/ 列表 / 删除 / 问答（多模态 RAG）。"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from careercrew_api import storage
from careercrew_api.attachment_context import AttachmentRejected
from careercrew_api.auth.dependencies import CurrentUser, require_admin
from careercrew_api.deps import get_runtime_dep
from careercrew_api.limits import user_stream_slot
from careercrew_api.mentions import MentionRejected
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError
from careercrew_api.schemas import KnowledgeAskRequest
from careercrew_api.sse import (
    CancellationEvent,
    done_event,
    error_event,
    friendly_error,
    stage_event,
    stream_agent,
    turn_done_fields,
)
from careercrew_api.upload_io import read_bounded

router = APIRouter()

_MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
_DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
_MAX_JOBS = 50

# 进程内上传任务表（单进程部署；多 worker 需换外部存储/队列）
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _new_job(filename: str, user_id: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "user_id": user_id,
            "filename": filename,
            "status": "queued",
            "stage": "queued",
            "progress": 0.0,
            "error": None,
            "result": None,
            "created_at": time.time(),
        }
        # 只淘汰已结束的旧任务（按创建时间），避免挤掉进行中的上传
        finished = sorted(
            ((jid, j["created_at"]) for jid, j in _jobs.items() if j["status"] in ("done", "error")),
            key=lambda kv: kv[1],
        )
        overflow = len(_jobs) - _MAX_JOBS
        for jid, _ in finished[: max(overflow, 0)]:
            del _jobs[jid]
    return job_id


def _run_ingest_job(rt: CareerCrewRuntime, job_id: str, save_path: str,
                    user_id: str, category: str = "", doc_name: str = "",
                    output_dir: str = "", visibility: str = "private") -> None:
    """后台线程执行入库，通过进度回调更新任务状态。"""

    def cb(stage: str, progress: float) -> None:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            job["status"] = "running"
            job["stage"] = stage
            job["progress"] = min(max(progress, 0.0), 1.0)

    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["status"] = "running"

    try:
        result = rt.ingest_document(
            save_path, user_id=user_id, progress_cb=cb, category=category,
            output_dir=output_dir or None, doc_name=doc_name, visibility=visibility,
        )
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.update(status="done", stage="done", progress=1.0, result=result)
    except Exception as e:  # noqa: BLE001 - 用户可见的解析/入库错误统一收口
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.update(status="error", error=friendly_error(e))


@router.post("/upload", status_code=202)
async def upload_knowledge(
    current_user: CurrentUser,
    file: UploadFile = File(...),
    category: str = Form(""),
    visibility: str = Form("private"),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """上传文档入库（异步）：立即返回 job_id，进度通过 GET /upload/{job_id} 轮询。

    category: 内容分类（resume/knowledge/interview），空串按文件名自动识别。
    visibility: private | public（公共库仅管理员可上传）。
    """
    if visibility not in ("private", "public"):
        raise HTTPException(status_code=422, detail="visibility 必须为 private 或 public")
    if visibility == "public" and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以发布公共知识库")

    # 大小校验在分块读取阶段生效（超限拒绝，不把超大 body 缓冲进内存）
    content = await read_bounded(file, _MAX_UPLOAD_SIZE)
    if content is None:
        raise HTTPException(status_code=413, detail="文件超过 50MB 限制")

    # 文件名防路径穿越：只取 basename（恶意文件名可含 ../ 或盘符）；
    # 原名仅存入任务元数据，磁盘键名为 UUID。
    filename = Path(file.filename or "upload").name or "upload"
    ext = Path(filename).suffix.lower()
    user_id = current_user["id"]
    job_id = _new_job(filename, user_id)
    save_path = storage.resolve_under(storage.L.knowledge_raw, user_id, f"{job_id}{ext}")

    def _write_raw() -> None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(content)

    # 写盘为阻塞 IO（可达 50MB），下放线程池避免卡事件循环
    await run_in_threadpool(_write_raw)

    output_dir = storage.resolve_under(storage.L.parsed_knowledge, user_id, job_id)
    threading.Thread(
        target=_run_ingest_job,
        args=(rt, job_id, str(save_path), user_id, category, filename, str(output_dir), visibility),
        daemon=True,
    ).start()
    return {
        "job_id": job_id,
        "filename": filename,
        "status": "queued",
        "stage": "queued",
        "progress": 0.0,
    }


@router.get("/upload/{job_id}")
def upload_status(job_id: str, current_user: CurrentUser) -> dict:
    """查询上传任务进度：{status, stage, progress, error, result}。"""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None or job.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=404, detail=f"上传任务不存在：{job_id}")
    return dict(job)


@router.get("")
def list_knowledge(
    current_user: CurrentUser,
    scope: str = "all",
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """知识库状态：总点数 + 文档列表。scope: all（公共+本人私有）/public/private。"""
    if scope not in ("all", "public", "private"):
        raise HTTPException(status_code=422, detail="scope 必须为 all / public / private")
    try:
        return rt.knowledge_status(current_user["id"], scope)
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.delete("/{doc_id}")
def delete_knowledge(
    doc_id: str,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """删除指定文档的全部向量点（私有仅本人；公共仅管理员）。"""
    try:
        deleted, public_blocked = rt.delete_document(
            current_user["id"], doc_id, is_admin=current_user["role"] == "admin"
        )
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if public_blocked:
        raise HTTPException(status_code=403, detail="只有管理员可以删除公共知识库文档")
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"知识文档不存在：{doc_id}")
    return {"deleted": deleted, "doc_id": doc_id}


@router.post("/{doc_id}/publish")
def publish_knowledge(
    doc_id: str,
    _: Annotated[dict[str, str], Depends(require_admin)],
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """管理员把自己名下的私有文档发布为公共。"""
    try:
        n = rt.publish_document(current_user["id"], doc_id)
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if n == 0:
        raise HTTPException(status_code=404, detail=f"知识文档不存在或不可发布：{doc_id}")
    return {"published": n, "doc_id": doc_id}


@router.post("/{doc_id}/unpublish")
def unpublish_knowledge(
    doc_id: str,
    _: Annotated[dict[str, str], Depends(require_admin)],
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """管理员下架公共文档（转为自己的私有）。"""
    try:
        n = rt.unpublish_document(current_user["id"], doc_id)
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if n == 0:
        raise HTTPException(status_code=404, detail=f"知识文档不存在或不可下架：{doc_id}")
    return {"unpublished": n, "doc_id": doc_id}


@router.post("/ask")
def ask_knowledge(
    req: KnowledgeAskRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
    _slot: None = Depends(user_stream_slot),
) -> StreamingResponse:
    """知识库问答：KnowledgeAdvisor 基于检索流式回答。

    事件流：{stage:knowledge} -> chunk xN -> {done, content, sources}。
    sources 为 agent 实际检索到的结构化片段，前端标注来源并可点击查看。
    """

    # T3.4 §15.2：mentions 服务端二次校验（ownership/visibility），拒绝越权引用。
    mention_dicts = [m.model_dump() for m in req.mentions]
    try:
        resolved_mentions = rt.resolve_mentions(current_user["id"], mention_dicts)
    except MentionRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    # T3.2：附件服务端校验所有权 + 读取内容（文本块）；整体拒绝 → 422。
    try:
        attachment_blocks = rt.resolve_attachment_blocks(
            current_user["id"], [a.model_dump() for a in req.attachments]
        )
    except AttachmentRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    def gen():
        result: dict = {"content": "", "sources": [], "turn": None}
        cancel = CancellationEvent()

        def _run(cb):
            nonlocal result
            res = rt.run_knowledge_ask_stream(
                req.question, current_user["id"], thread_id=req.thread_id, cb=cb,
                category=req.category, scope=req.scope, mentions=resolved_mentions,
                attachments=attachment_blocks,
                cancel_check=cancel.check, tools=req.tools,
            )
            if hasattr(res, "content"):
                result = {
                    "content": res.content,
                    "sources": getattr(res, "sources", []),
                    "turn": getattr(res, "turn", None),
                }
            else:
                result = {
                    "content": res.get("content", ""),
                    "sources": res.get("sources", []),
                    "turn": None,
                }

        failed = False
        try:
            yield stage_event("knowledge")
            content_parts: list[str] = []
            # agentic 检索 + VLM 读图可能长时间无文本 chunk，统一空闲超时（与会诊一致）
            for line in stream_agent(_run, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "error":
                    failed = True
                elif evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            # 最终内容以 agent 最后一轮回答为准（流式 chunk 可能含中间轮开头话）
            # 出错时不补发 done，避免前端错误提示被空回答覆盖
            if not failed:
                yield done_event(
                    result.get("content") or "".join(content_parts),
                    sources=result.get("sources", []),
                    **turn_done_fields(result.get("turn")),
                )
        except RuntimeInitError as e:
            yield error_event(friendly_error(e))
        except Exception as e:
            yield error_event(friendly_error(e))

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/image")
def knowledge_image(
    path: str,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> FileResponse:
    """返回知识库图片文件（页面图 / 对象裁剪图），供前端标注来源时内嵌与放大查看。

    安全约束：路径必须解析到 data/ 目录内且为真实文件，防止目录穿越读取任意文件。
    """
    root = _DATA_ROOT.resolve()
    p = Path(path).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    try:
        owned = rt.knowledge_asset_owned(current_user["id"], str(p))
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if not owned:
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(p)
