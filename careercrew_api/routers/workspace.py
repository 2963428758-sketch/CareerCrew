"""Phase 8 workspace APIs: message search, traceability, and follow-up work."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.workspace.traceability import WorkspaceTraceability
from careercrew_core.workspace.consultation import ConsultationWorkspace
from careercrew_core.workspace.resume import ResumeWorkspace

router = APIRouter()


class BookmarkRequest(BaseModel):
    note: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=20)


class BranchRequest(BaseModel):
    source_thread_id: str = Field(min_length=1, max_length=200)
    cutoff_message_id: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=255)


class ActionItemRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=2000)
    due_date: str | None = Field(default=None, max_length=10)


class ActionItemPatch(BaseModel):
    status: str = Field(pattern="^(open|done|dismissed)$")


class ConsultationReportRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=100)


class ConsultationStatusPatch(BaseModel):
    status: str = Field(pattern="^(draft|confirmed)$")
    version: int = Field(ge=1)


class ConsultationPlanRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    steps: list[dict] = Field(min_length=1, max_length=50)


class ResumeMasterRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50000)
    description: str = Field(default="", max_length=1000)


class ResumeVersionRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=50000)
    parent_version_id: str | None = Field(default=None, max_length=100)
    kind: str = Field(default="derived", pattern="^(master|derived)$")


class ResumeMaterialRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    context: str = Field(default="", max_length=5000)
    role: str = Field(default="", max_length=2000)
    actions: str = Field(default="", max_length=5000)
    results: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class ResumeAnnotationRequest(BaseModel):
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    note: str = Field(min_length=1, max_length=1000)


class ResumeExportRequest(BaseModel):
    version_ids: list[str] = Field(min_length=1, max_length=20)
    formats: list[str] = Field(min_length=1, max_length=2)


def _workspace(rt: CareerCrewRuntime) -> WorkspaceTraceability:
    rt._ensure_stores()
    store = getattr(rt, "conversation_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="对话存储尚未就绪")
    service = getattr(rt, "workspace_traceability", None)
    if service is None:
        service = WorkspaceTraceability(store)
        setattr(rt, "workspace_traceability", service)
    return service


def _consultation(rt: CareerCrewRuntime) -> ConsultationWorkspace:
    rt._ensure_stores()
    store = getattr(rt, "conversation_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="对话存储尚未就绪")
    service = getattr(rt, "consultation_workspace", None)
    if service is None:
        service = ConsultationWorkspace(store)
        setattr(rt, "consultation_workspace", service)
    return service


def _resume_workspace(rt: CareerCrewRuntime) -> ResumeWorkspace:
    rt._ensure_stores()
    store = getattr(rt, "conversation_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="简历工作台尚未就绪")
    service = getattr(rt, "resume_workspace", None)
    if service is None:
        service = ResumeWorkspace(store)
        setattr(rt, "resume_workspace", service)
    return service


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _not_found(exc: PermissionError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("/workspace/search")
def search_workspace(
    user: CurrentUser,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=50),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        return _workspace(rt).search(q, user["id"], limit)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/workspace/bookmarks")
def list_bookmarks(
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    return _workspace(rt).list_bookmarks(user["id"])


@router.put("/workspace/messages/{message_id}/bookmark")
def upsert_bookmark(
    message_id: str,
    payload: BookmarkRequest,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        return _workspace(rt).upsert_bookmark(
            user["id"], message_id, note=payload.note, tags=payload.tags,
        )
    except PermissionError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.delete("/workspace/messages/{message_id}/bookmark")
def delete_bookmark(
    message_id: str,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    # Validate ownership before deletion so a foreign message is indistinguishable
    # from a missing one and cannot be used as an existence oracle.
    try:
        service = _workspace(rt)
        service._message(user["id"], message_id)
    except PermissionError as exc:
        raise _not_found(exc) from exc
    if not service.delete_bookmark(user["id"], message_id):
        raise HTTPException(status_code=404, detail="书签不存在")
    return {"ok": True}


@router.post("/workspace/branches", status_code=201)
def create_branch(
    payload: BranchRequest,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        return _workspace(rt).create_branch(
            user["id"], payload.source_thread_id, payload.cutoff_message_id,
            title=payload.title,
        )
    except PermissionError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/workspace/branches")
def list_branches(
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    return _workspace(rt).list_branches(user["id"])


@router.post("/workspace/action-items", status_code=201)
def create_action_item(
    payload: ActionItemRequest,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        return _workspace(rt).create_action_item(
            user["id"], payload.message_id, title=payload.title,
            note=payload.note, due_date=payload.due_date,
        )
    except PermissionError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/workspace/action-items")
def list_action_items(
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    return _workspace(rt).list_action_items(user["id"])


@router.patch("/workspace/action-items/{item_id}")
def update_action_item(
    item_id: str,
    payload: ActionItemPatch,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        row = _workspace(rt).update_action_item(
            user["id"], item_id, status=payload.status,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="行动项不存在或不属于当前账号")
    return row


# ── 可解释会诊与执行计划 ──


@router.post("/workspace/consult-reports", status_code=201)
def create_consultation_report(
    payload: ConsultationReportRequest,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        return _consultation(rt).save_report(user["id"], payload.message_id)
    except PermissionError as exc:
        raise _not_found(exc) from exc


@router.get("/workspace/consult-reports")
def list_consultation_reports(
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    return _consultation(rt).list_reports(user["id"])


@router.get("/workspace/consult-reports/{report_id}")
def get_consultation_report(
    report_id: str,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    row = _consultation(rt).get_report(user["id"], report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会诊报告不存在或不属于当前账号")
    return row


@router.patch("/workspace/consult-reports/{report_id}")
def update_consultation_report(
    report_id: str,
    payload: ConsultationStatusPatch,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        row = _consultation(rt).update_report(
            user["id"], report_id, status=payload.status, version=payload.version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="会诊报告不存在或不属于当前账号")
    return row


@router.post("/workspace/consult-reports/{report_id}/plans", status_code=201)
def create_consultation_plan(
    report_id: str,
    payload: ConsultationPlanRequest,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        row = _consultation(rt).create_plan(
            user["id"], report_id, title=payload.title, steps=payload.steps,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="会诊报告不存在或不属于当前账号")
    return row


@router.get("/workspace/consult-reports/{report_id}/plans")
def list_consultation_plans(
    report_id: str,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    service = _consultation(rt)
    if service.get_report(user["id"], report_id) is None:
        raise HTTPException(status_code=404, detail="会诊报告不存在或不属于当前账号")
    return service.list_plans(user["id"], report_id)


@router.patch("/workspace/consult-plans/{plan_id}")
def update_consultation_plan(
    plan_id: str,
    payload: ConsultationStatusPatch,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        row = _consultation(rt).update_plan(
            user["id"], plan_id, status=payload.status, version=payload.version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="执行计划不存在或不属于当前账号")
    return row


# ── 通用简历母版工作台 ──


@router.post("/workspace/resumes/masters", status_code=201)
def create_resume_master(
    payload: ResumeMasterRequest,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        return _resume_workspace(rt).create_master(
            user["id"], title=payload.title, content=payload.content,
            description=payload.description,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/workspace/resumes/masters")
def list_resume_masters(
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    return _resume_workspace(rt).list_masters(user["id"])


@router.get("/workspace/resumes/masters/{master_id}")
def get_resume_master(
    master_id: str,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    row = _resume_workspace(rt).get_master(user["id"], master_id)
    if row is None:
        raise HTTPException(status_code=404, detail="简历母版不存在或不属于当前账号")
    return row


@router.get("/workspace/resumes/masters/{master_id}/versions")
def list_resume_versions(
    master_id: str,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    service = _resume_workspace(rt)
    if service.get_master(user["id"], master_id) is None:
        raise HTTPException(status_code=404, detail="简历母版不存在或不属于当前账号")
    return service.list_versions(user["id"], master_id)


@router.post("/workspace/resumes/masters/{master_id}/versions", status_code=201)
def create_resume_version(
    master_id: str,
    payload: ResumeVersionRequest,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        return _resume_workspace(rt).create_version(
            user["id"], master_id, label=payload.label, content=payload.content,
            parent_version_id=payload.parent_version_id, kind=payload.kind,
        )
    except PermissionError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/workspace/resumes/diff")
def diff_resume_versions(
    user: CurrentUser,
    left_version_id: str = Query(..., min_length=1, max_length=100),
    right_version_id: str = Query(..., min_length=1, max_length=100),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    row = _resume_workspace(rt).diff_versions(user["id"], left_version_id, right_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="简历版本不存在、不属于当前账号或不在同一母版")
    return row


@router.post("/workspace/resumes/materials", status_code=201)
def create_resume_material(
    payload: ResumeMaterialRequest,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        return _resume_workspace(rt).create_material(user["id"], **payload.model_dump())
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/workspace/resumes/materials")
def list_resume_materials(
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    return _resume_workspace(rt).list_materials(user["id"])


@router.post("/workspace/resumes/versions/{version_id}/annotations", status_code=201)
def create_resume_annotation(
    version_id: str,
    payload: ResumeAnnotationRequest,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        return _resume_workspace(rt).create_annotation(
            user["id"], version_id, start_offset=payload.start_offset,
            end_offset=payload.end_offset, note=payload.note,
        )
    except PermissionError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/workspace/resumes/versions/{version_id}/annotations")
def list_resume_annotations(
    version_id: str,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    return _resume_workspace(rt).list_annotations(user["id"], version_id)


@router.post("/workspace/resumes/exports", status_code=202)
def create_resume_export(
    payload: ResumeExportRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    try:
        service = _resume_workspace(rt)
        job = service.create_export_job(user["id"], payload.version_ids, payload.formats)
    except PermissionError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc
    background_tasks.add_task(service.run_export_job, user["id"], job["id"])
    return job


@router.get("/workspace/resumes/exports")
def list_resume_exports(
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> list[dict]:
    return _resume_workspace(rt).list_export_jobs(user["id"])


@router.get("/workspace/resumes/exports/{job_id}")
def get_resume_export(
    job_id: str,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    rows = [row for row in _resume_workspace(rt).list_export_jobs(user["id"])
            if row["id"] == job_id]
    if not rows:
        raise HTTPException(status_code=404, detail="导出任务不存在或不属于当前账号")
    return rows[0]


@router.get("/workspace/resumes/exports/{job_id}/download")
def download_resume_export(
    job_id: str,
    user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> Response:
    try:
        body = _resume_workspace(rt).download_export(user["id"], job_id)
    except PermissionError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        body, media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=resume-export.zip",
                 "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
