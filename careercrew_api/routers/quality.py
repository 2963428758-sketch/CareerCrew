"""Reviewer-only, privacy-safe quality read APIs.

These routes intentionally read dedicated quality views rather than ordinary
conversation/message endpoints.  The response contracts exclude user prose,
thread/message identifiers, and raw retrieval/tool payloads.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from careercrew_api.auth.dependencies import QualityReviewer
from careercrew_api.deps import get_runtime_dep
from careercrew_core.conversation.db import _json_dumps
from careercrew_core.conversation.store import OwnershipError

router = APIRouter()


def _parse_dt(value: datetime | None) -> datetime | None:
    """Normalize a query datetime into a tz-aware UTC value."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ReviewUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    root_cause: Literal["llm", "prompt", "rag_retrieval", "reranker", "tool",
                        "context", "ambiguous_question", "product_bug", "unknown"] | None = None
    # promoted_to_eval 在枚举内但状态机拒绝（409）：只能由 Promote API 设置。
    status: Literal["new", "triaged", "fixed", "ignored", "promoted_to_eval"]
    note: str | None = None


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="质检记录不存在或无可访问内容")


@router.get("/metrics")
def quality_metrics(reviewer: QualityReviewer, rt=Depends(get_runtime_dep),
                    from_: datetime | None = Query(None, alias="from"),
                    to: datetime | None = Query(None),
                    module: str | None = Query(None, max_length=50),
                    agent: str | None = Query(None, max_length=100),
                    model: str | None = Query(None, max_length=150),
                    prompt_version: str | None = Query(None, max_length=80),
                    agent_version: str | None = Query(None, max_length=80)) -> dict:
    """Dashboard aggregates: helpful rate with sample size, coverage, reason
    distribution, failure shares, latency/token stats, version trend and the
    unversioned-run alert (§25.2 / §25.3 / §44 / T5.5)."""
    rt._ensure_heavy()
    filters = {
        "from_dt": _parse_dt(from_),
        "to_dt": _parse_dt(to),
        "module": module, "agent": agent, "model": model,
        "prompt_version": prompt_version, "agent_version": agent_version,
    }
    return rt.conversation_store.compute_quality_metrics(filters)


@router.get("/bad-cases")
def list_bad_cases(reviewer: QualityReviewer, rt=Depends(get_runtime_dep)) -> list[dict]:
    """List all negative-feedback metadata without comments or conversation data."""
    rt._ensure_heavy()
    return rt.conversation_store.list_quality_feedback()


@router.get("/bad-cases/{feedback_id}")
def get_bad_case(feedback_id: str, reviewer: QualityReviewer, rt=Depends(get_runtime_dep)) -> dict:
    """Return one negative-feedback metadata row; content remains in the snapshot endpoint."""
    rt._ensure_heavy()
    feedback = rt.conversation_store.get_quality_feedback(feedback_id)
    if feedback is None:
        raise _not_found()
    return feedback


@router.get("/bad-cases/{feedback_id}/review")
def get_bad_case_review(feedback_id: str, reviewer: QualityReviewer,
                        rt=Depends(get_runtime_dep)) -> dict:
    """Return the reviewer's attribution row (root cause / status / note)."""
    rt._ensure_heavy()
    review = rt.conversation_store.get_quality_review(feedback_id)
    if review is None:
        raise _not_found()
    return review


@router.put("/bad-cases/{feedback_id}/review")
def update_bad_case_review(feedback_id: str, req: ReviewUpdateRequest, reviewer: QualityReviewer,
                           rt=Depends(get_runtime_dep)) -> dict:
    """Apply one attribution change; illegal transitions are rejected with 409."""
    rt._ensure_heavy()
    try:
        review = rt.conversation_store.update_quality_review(
            reviewer["id"], feedback_id, root_cause=req.root_cause,
            status=req.status, note=req.note,
        )
    except OwnershipError as exc:
        raise _not_found() from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return review


@router.get("/bad-cases/{feedback_id}/snapshot")
def get_bad_case_snapshot(feedback_id: str, reviewer: QualityReviewer,
                          rt=Depends(get_runtime_dep)) -> dict:
    """Return an unexpired, consented redacted snapshot and audit this access."""
    rt._ensure_heavy()
    snapshot = rt.conversation_store.get_quality_snapshot(feedback_id, reviewer["id"])
    if snapshot is None:
        raise _not_found()
    return snapshot


@router.get("/bad-cases/{feedback_id}/diagnostics")
def get_bad_case_diagnostics(feedback_id: str, reviewer: QualityReviewer,
                             rt=Depends(get_runtime_dep)) -> dict:
    """Return whitelisted run/retrieval/tool metadata for a negative-feedback run."""
    rt._ensure_heavy()
    diagnostics = rt.conversation_store.get_quality_diagnostics(feedback_id)
    if diagnostics is None:
        raise _not_found()
    return diagnostics


class EvalCaseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: Literal["draft", "approved", "deprecated"] | None = None
    target_agent: str | None = None
    input_text: str | None = None
    context: dict | None = None
    expected_behavior: str | None = None
    rubric: dict | None = None
    failure_reason: str | None = None


@router.post("/bad-cases/{feedback_id}/promote")
def promote_bad_case(feedback_id: str, reviewer: QualityReviewer,
                     rt=Depends(get_runtime_dep)) -> dict:
    """Promote a shared-context negative feedback into an eval case draft (§29)."""
    rt._ensure_heavy()
    try:
        case = rt.conversation_store.promote_to_eval(reviewer["id"], feedback_id)
    except OwnershipError as exc:
        raise _not_found() from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return case


@router.get("/eval-cases/export")
def export_eval_cases(reviewer: QualityReviewer, rt=Depends(get_runtime_dep)) -> str:
    """Versioned JSONL export of approved eval cases（§30）。"""
    rt._ensure_heavy()
    rows = rt.conversation_store.export_eval_cases()
    return "\n".join(_json_dumps(row) for row in rows) + ("\n" if rows else "")


@router.get("/eval-cases")
def list_eval_cases(reviewer: QualityReviewer, rt=Depends(get_runtime_dep),
                    status: str | None = Query(None)) -> list[dict]:
    rt._ensure_heavy()
    try:
        return rt.conversation_store.list_eval_cases(status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/eval-cases/{case_id}")
def get_eval_case(case_id: str, reviewer: QualityReviewer,
                  rt=Depends(get_runtime_dep)) -> dict:
    rt._ensure_heavy()
    case = rt.conversation_store.get_eval_case(case_id)
    if case is None:
        raise _not_found()
    return case


@router.put("/eval-cases/{case_id}")
def update_eval_case(case_id: str, req: EvalCaseUpdateRequest, reviewer: QualityReviewer,
                     rt=Depends(get_runtime_dep)) -> dict:
    rt._ensure_heavy()
    try:
        return rt.conversation_store.update_eval_case(reviewer["id"], case_id,
                                                      fields=req.model_dump(exclude_unset=True))
    except OwnershipError as exc:
        raise _not_found() from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/eval-cases/{case_id}/approve")
def approve_eval_case(case_id: str, reviewer: QualityReviewer,
                      rt=Depends(get_runtime_dep)) -> dict:
    rt._ensure_heavy()
    try:
        return rt.conversation_store.approve_eval_case(reviewer["id"], case_id)
    except OwnershipError as exc:
        raise _not_found() from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
