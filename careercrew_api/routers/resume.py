"""resume 路由：上传（异步任务 + 简历库）+ 简历优化流式。

上传类型识别：
- 图片（png/jpg/...）-> read_image 视觉描述
- txt/md/markdown -> MarkdownLoader
- pdf/doc/docx/... -> MinerU 解析（runtime.load_document）
- >200k 字符截断标记 truncated:true

上传与知识库一致改为异步任务：POST /upload 立即返回 job_id，
GET /upload/{job_id} 轮询进度（queued -> parse -> done），解析结果
写入简历库（data/parsed/resumes/{user_id}/{resume_id}/content.txt + meta.json），
原件按 UUID 落 data/uploads/resumes_raw/{user_id}/{uuid}.{ext}，
前端可在「简历管理」面板复用历史简历。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
import time
import uuid
from collections.abc import Generator
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from careercrew_api import storage
from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.limits import user_stream_slot
from careercrew_api.request_helpers import (
    ndjson_response as _ndjson_response,
)
from careercrew_api.request_helpers import (
    resolve_attachments_or_422 as _resolve_attachments,
)
from careercrew_api.request_helpers import (
    resolve_mentions_or_422 as _resolve_mentions,
)
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError
from careercrew_api.schemas import GenerateRequest, ResumeChatRequest
from careercrew_api.sse import (
    CancellationEvent,
    done_event,
    error_event,
    friendly_error,
    stage_event,
    stream_agent,
)
from careercrew_api.upload_io import read_bounded

router = APIRouter()

_MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20MB
_MAX_CONTENT_CHARS = 200_000
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
_TEXT_EXTS = {".txt", ".md", ".markdown"}
_MAX_JOBS = 50
_RESUME_ID_RE = re.compile(r"^[0-9a-f]{12}$")

# 进程内上传任务表（单进程部署；多 worker 需换外部存储/队列）
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _resume_path(user_id: str, thread_id: str) -> Path:
    # Public thread ids are untrusted path input. Keep the public id in the API,
    # but use a stable opaque filename under the authenticated user's directory.
    digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()
    return storage.resolve_under(storage.L.resume_threads, user_id, f"{digest}.txt")


def _resume_lib_dir(user_id: str, resume_id: str) -> Path:
    """简历库条目目录（内容 + 元数据），resume_id 必须为 12 位 hex（UUID 键）。"""
    if not _RESUME_ID_RE.match(resume_id):
        raise ValueError(f"非法简历 ID: {resume_id}")
    return storage.resolve_under(storage.L.parsed_resumes, user_id, resume_id)


def _load_resume(user_id: str, thread_id: str) -> str:
    try:
        return _resume_path(user_id, thread_id).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _save_resume(user_id: str, thread_id: str, text: str) -> None:
    path = _resume_path(user_id, thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def _clean_text(text: str) -> str:
    """清理解析产生的表格碎片（Word 排版 -> markdown 表格）+ 压缩连续空行。"""
    cleaned_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")]
            cells = [c for c in cells if c]  # 去掉空单元格
            if not cells:
                continue  # 全空 -> 删
            if all(set(c) <= set("-: ") for c in cells):
                continue  # 分隔行 |---|---| -> 删
            cleaned_lines.append("  ".join(cells))  # 有内容 -> 只留内容
        else:
            cleaned_lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines))


def _parse_resume_file(rt: CareerCrewRuntime, path: str, ext: str,
                       output_dir: str | None = None) -> tuple[str, str]:
    """按扩展名解析简历 -> (doc_type, text)；解析失败抛异常（带用户可读信息）。"""
    if ext in _IMAGE_EXTS:
        try:
            return "image", rt.read_image(path)
        except Exception as e:
            raise RuntimeError(f"图片识别失败：{e}") from e
    if ext in _TEXT_EXTS:
        return "text", Path(path).read_text(encoding="utf-8", errors="replace")
    doc_type = ext.lstrip(".") or "unknown"
    try:
        return doc_type, rt.load_document(path, output_dir=output_dir)
    except RuntimeInitError as e:
        raise RuntimeError(str(e)) from e
    except Exception as e:
        raise RuntimeError(f"文件解析失败（{doc_type} 格式）：{e}") from e


def _run_upload_job(rt: CareerCrewRuntime, job_id: str, save_path: str,
                    filename: str, ext: str, user_id: str) -> None:
    """后台线程解析简历并写入简历库，通过任务状态向前端反馈进度。"""

    def _set(**updates: object) -> None:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.update(**updates)

    _set(status="running", stage="parse", progress=0.1)
    try:
        doc_type, text = _parse_resume_file(
            rt, save_path, ext, output_dir=str(storage.resolve_under(storage.L.parsed_resumes, user_id, job_id))
        )
        truncated = False
        if len(text) > _MAX_CONTENT_CHARS:
            text = text[:_MAX_CONTENT_CHARS]
            truncated = True
        text = _clean_text(text)

        resume_id = uuid.uuid4().hex[:12]
        lib_dir = _resume_lib_dir(user_id, resume_id)
        lib_dir.mkdir(parents=True, exist_ok=True)
        (lib_dir / "content.txt").write_text(text, encoding="utf-8")
        meta = {
            "resume_id": resume_id,
            "user_id": user_id,
            # 上传任务 id：原件（resumes_raw/{user}/{job_id}{ext}）与 MinerU
            # 解析产物目录（parsed/resumes/{user}/{job_id}/）的磁盘键名，
            # 删除简历时据此连带清理，避免磁盘只进不出。
            "job_id": job_id,
            "filename": filename,
            "doc_type": doc_type,
            "char_count": len(text),
            "truncated": truncated,
            "created_at": time.time(),
        }
        (lib_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        _set(status="done", stage="done", progress=1.0, result={**meta, "content": text})
    except RuntimeInitError as e:
        _set(status="error", error=friendly_error(e))
    except Exception as e:  # noqa: BLE001 - 用户可见的解析错误统一收口
        _set(status="error", error=friendly_error(e))


@router.post("/upload", status_code=202)
async def upload(
    current_user: CurrentUser,
    file: UploadFile = File(...),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """上传简历文件（异步）：立即返回 job_id，进度通过 GET /upload/{job_id} 轮询。

    与知识库上传一致：解析在后台线程执行，完成写入简历库供复用。
    大小校验在分块读取阶段生效（超限拒绝，不把超大 body 缓冲进内存）；
    写盘为阻塞 IO，下放线程池避免卡事件循环。
    """
    content_bytes = await read_bounded(file, _MAX_UPLOAD_SIZE)
    if content_bytes is None:
        raise HTTPException(status_code=413, detail="文件超过 20MB 限制")

    # 文件名防路径穿越：只取 basename（恶意文件名可含 ../ 或盘符）；
    # 原名仅存入任务元数据，磁盘键名为 UUID。
    filename = Path(file.filename or "upload").name or "upload"
    ext = Path(filename).suffix.lower()
    user_id = current_user["id"]
    job_id = _new_job(filename, user_id)
    save_path = storage.resolve_under(storage.L.resumes_raw, user_id, f"{job_id}{ext}")

    def _write_raw() -> None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(content_bytes)

    await run_in_threadpool(_write_raw)

    threading.Thread(
        target=_run_upload_job,
        args=(rt, job_id, str(save_path), filename, ext, user_id),
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


@router.get("/library")
def list_library(current_user: CurrentUser) -> dict:
    """简历库：全部已上传简历的元数据（按上传时间倒序）。"""
    user_dir = storage.L.parsed_resumes / current_user["id"]
    items: list[dict] = []
    if user_dir.exists():
        for meta_path in user_dir.glob("*/meta.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - 元数据损坏时跳过单条，不影响整体列表
                continue
            if meta.get("user_id") != current_user["id"]:
                continue
            items.append(meta)
    items.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    return {"resumes": items}


@router.get("/library/{resume_id}/content")
def library_content(resume_id: str, current_user: CurrentUser) -> dict:
    """读取某份简历的解析文本（供「用于当前对话」复用）。"""
    try:
        lib_dir = _resume_lib_dir(current_user["id"], resume_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=f"简历不存在：{resume_id}") from ve
    meta_path = lib_dir / "meta.json"
    txt_path = lib_dir / "content.txt"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        meta = {}
    if meta.get("user_id") != current_user["id"] or not txt_path.is_file():
        raise HTTPException(status_code=404, detail=f"简历不存在：{resume_id}")
    return {"resume_id": resume_id, "content": txt_path.read_text(encoding="utf-8")}


@router.delete("/library/{resume_id}")
def delete_library(resume_id: str, current_user: CurrentUser) -> dict:
    """从简历库删除某份简历：条目目录 + 原件 + 解析产物目录一并清理。"""
    try:
        lib_dir = _resume_lib_dir(current_user["id"], resume_id)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=f"简历不存在：{resume_id}") from ve
    meta_path = lib_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        meta = {}
    if meta.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=404, detail=f"简历不存在：{resume_id}")
    removed = 0
    for name in ("content.txt", "meta.json"):
        p = lib_dir / name
        if p.is_file():
            p.unlink()
            removed += 1
    if removed == 0:
        raise HTTPException(status_code=404, detail=f"简历不存在：{resume_id}")

    # 连带清理磁盘残留（尽力而为）：原件 + MinerU 解析产物目录 + 条目目录本身。
    # 存量旧条目的 meta 无 job_id 记录，只能清掉条目目录，原件需脚本兜底。
    job_id = str(meta.get("job_id") or "")
    user_id = current_user["id"]
    if _RESUME_ID_RE.match(job_id):
        raw_dir = storage.L.resumes_raw / user_id
        try:
            if raw_dir.is_dir():
                for f in raw_dir.iterdir():
                    # stem 精确匹配而非 glob，防 job_id 含通配符注入
                    if f.is_file() and f.stem == job_id:
                        f.unlink(missing_ok=True)
            parse_dir = storage.resolve_under(storage.L.parsed_resumes, user_id, job_id)
            if parse_dir.is_dir():
                shutil.rmtree(parse_dir, ignore_errors=True)
        except OSError:
            logging.getLogger(__name__).exception(
                "简历磁盘清理失败：%s/%s", user_id, job_id
            )
    shutil.rmtree(lib_dir, ignore_errors=True)
    return {"deleted": resume_id}


@router.post("/generate")
def generate(
    req: GenerateRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
    _slot: None = Depends(user_stream_slot),
) -> StreamingResponse:
    """简历顾问以"上传简历 + 目标 JD"为输入流式优化。"""

    def gen() -> Generator[str, None, None]:
        cancel = CancellationEvent()

        def run_fn(cb):
            from langchain_core.messages import HumanMessage

            user_id = current_user["id"]
            episodic = rt._get_episodic(req.thread_id, user_id)
            agent = rt.new_resume_advisor(cb, episodic=episodic)
            prompt = f"我的简历：\n{req.user_resume}\n\n目标 JD：\n{req.jd or '未指定'}\n\n请帮我优化简历。"
            state = {
                "thread_id": req.thread_id, "user_id": user_id, "stage": "resume",
                "user_intent": prompt,
                "messages": [HumanMessage(content=prompt)],
                "pending_action": None, "agent_outputs": {}, "target_companies": [],
            }
            cancel.check()
            agent.run(state)
            cancel.check()

        failed = False
        try:
            yield stage_event("resume")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "error":
                    failed = True
                elif evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            if not failed:
                yield done_event("".join(content_parts))
        except Exception as e:
            yield error_event(friendly_error(e))

    return _ndjson_response(gen())


@router.post("/chat")
def chat(
    req: ResumeChatRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
    _slot: None = Depends(user_stream_slot),
) -> StreamingResponse:
    """对话式简历优化：简历按 thread 持久化，多轮提问 / 追问优化。

    - resume_text 非空：新上传的简历，写入该线程存储（后续轮次自动复用）
    - 对话历史由 BaseAgent.history_loader 从 episodic 恢复，这里只放当前输入
    - 每轮 done 后落库 user/agent transcript，刷新可恢复
    """

    mentions = _resolve_mentions(rt, current_user["id"], req.mentions)
    attachment_blocks = _resolve_attachments(rt, current_user["id"], req.attachments)

    def gen() -> Generator[str, None, None]:
        result: dict = {"content": ""}
        cancel = CancellationEvent()

        def run_fn(cb):
            nonlocal result
            from langchain_core.messages import HumanMessage

            from careercrew_api.attachment_context import build_user_message

            user_id = current_user["id"]
            episodic = rt._get_episodic(req.thread_id, user_id)
            agent = rt.new_resume_advisor(
                cb, episodic=episodic,
                allowed=rt.compute_effective_tools("resume", req.tools),
                hitl_requires=rt._hitl_requires(),
                forced_doc_ids=rt._mention_knowledge_ids(mentions),
            )
            if req.resume_text.strip():
                _save_resume(user_id, req.thread_id, req.resume_text)
            resume = req.resume_text.strip() or _load_resume(user_id, req.thread_id)
            try:
                pending_id = rt.record_user_message(
                    user_id, req.thread_id, req.question, module="resume"
                )
            except Exception:
                pending_id = None
            if resume:
                current = (
                    f"我的简历：\n{resume}\n\n"
                    f"目标 JD：\n{req.jd or '未指定'}\n\n"
                    f"用户问题：{req.question}"
                )
            else:
                current = req.question
            state = {
                "thread_id": req.thread_id, "user_id": user_id, "stage": "resume",
                "user_intent": current,
                "messages": [HumanMessage(content=build_user_message(
                    current, attachment_blocks + rt._mention_blocks(user_id, mentions)
                ))],
                "pending_action": None, "agent_outputs": {}, "target_companies": [],
                "pending_user_entry_id": pending_id,
            }
            cancel.check()
            agent.run(state)
            cancel.check()
            lr = agent.last_result
            result["content"] = (getattr(lr, "content", "") or "").strip() if lr is not None else ""

        failed = False
        try:
            yield stage_event("resume")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "error":
                    failed = True
                elif evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            if failed:
                return
            # 最终内容以 agent.last_result 为准（流式 chunk 含中间轮次开头，会重复）
            content = result["content"] or "".join(content_parts)
            try:
                rt.record_thread_messages(
                    current_user["id"], req.thread_id, user_text="", agent_text=content,
                    module="resume",
                )
            except Exception:
                pass  # transcript 写入失败不阻塞主流程
            yield done_event(content)
        except Exception as e:
            yield error_event(friendly_error(e))

    return _ndjson_response(gen())
