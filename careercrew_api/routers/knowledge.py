"""知识库路由：异步上传入库（任务 + 进度查询）/ 列表 / 删除 / 问答（多模态 RAG）。"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError
from careercrew_api.schemas import KnowledgeAskRequest
from careercrew_api.sse import done_event, error_event, stage_event, stream_agent

router = APIRouter()

_MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"
_MAX_JOBS = 50

# 进程内上传任务表（单进程部署；多 worker 需换外部存储/队列）
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _new_job(filename: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
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


def _run_ingest_job(rt: CareerCrewRuntime, job_id: str, save_path: str) -> None:
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
        result = rt.ingest_document(save_path, progress_cb=cb)
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.update(status="done", stage="done", progress=1.0, result=result)
    except RuntimeInitError as e:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.update(status="error", error=str(e))
    except Exception as e:  # noqa: BLE001 - 用户可见的解析/入库错误统一收口
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.update(status="error", error=f"解析入库失败：{e}")


@router.post("/upload", status_code=202)
async def upload_knowledge(
    file: UploadFile = File(...),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """上传文档入库（异步）：立即返回 job_id，进度通过 GET /upload/{job_id} 轮询。"""
    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="文件超过 50MB 限制")

    # 文件名防路径穿越：只取 basename（恶意文件名可含 ../ 或盘符）
    filename = Path(file.filename or "upload").name or "upload"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    save_path = UPLOAD_DIR / filename
    save_path.write_bytes(content)

    job_id = _new_job(filename)
    threading.Thread(
        target=_run_ingest_job,
        args=(rt, job_id, str(save_path)),
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
def upload_status(job_id: str) -> dict:
    """查询上传任务进度：{status, stage, progress, error, result}。"""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"上传任务不存在：{job_id}")
    return dict(job)


@router.get("")
def list_knowledge(
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """知识库状态：总点数 + 文档列表。"""
    try:
        return rt.knowledge_status()
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.delete("/{doc_id}")
def delete_knowledge(
    doc_id: str,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """删除指定文档的全部向量点。"""
    try:
        n = rt.delete_document(doc_id)
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"deleted": n, "doc_id": doc_id}


@router.post("/ask")
def ask_knowledge(
    req: KnowledgeAskRequest,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> StreamingResponse:
    """知识库问答：KnowledgeAdvisor 基于检索流式回答。

    事件流：{stage:knowledge} -> chunk xN -> {done, content, sources}。
    sources 为 agent 实际检索到的结构化片段，前端标注来源并可点击查看。
    """

    def gen():
        result: dict = {"content": "", "sources": []}

        def _run(cb):
            nonlocal result
            result = rt.run_knowledge_ask_stream(req.question, req.user_id, cb)

        try:
            yield stage_event("knowledge")
            content_parts: list[str] = []
            for line in stream_agent(_run, timeout=120.0):
                evt = json.loads(line)
                if evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            yield done_event("".join(content_parts), sources=result.get("sources", []))
        except RuntimeInitError as e:
            yield error_event(str(e))
        except Exception as e:
            yield error_event(str(e))

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
