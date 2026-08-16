"""Reviewer-only, privacy-safe quality read APIs.

These routes intentionally read dedicated quality views rather than ordinary
conversation/message endpoints.  The response contracts exclude user prose,
thread/message identifiers, and raw retrieval/tool payloads.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from careercrew_api.auth.dependencies import QualityReviewer
from careercrew_api.deps import get_runtime_dep

router = APIRouter()


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="质检记录不存在或无可访问内容")


@router.get("/bad-cases")
def list_bad_cases(reviewer: QualityReviewer, rt=Depends(get_runtime_dep)) -> list[dict]:
    """List all negative-feedback metadata without comments or conversation data."""
    return rt.conversation_store.list_quality_feedback()


@router.get("/bad-cases/{feedback_id}")
def get_bad_case(feedback_id: str, reviewer: QualityReviewer, rt=Depends(get_runtime_dep)) -> dict:
    """Return one negative-feedback metadata row; content remains in the snapshot endpoint."""
    feedback = rt.conversation_store.get_quality_feedback(feedback_id)
    if feedback is None:
        raise _not_found()
    return feedback


@router.get("/bad-cases/{feedback_id}/snapshot")
def get_bad_case_snapshot(feedback_id: str, reviewer: QualityReviewer,
                          rt=Depends(get_runtime_dep)) -> dict:
    """Return an unexpired, consented redacted snapshot and audit this access."""
    snapshot = rt.conversation_store.get_quality_snapshot(feedback_id, reviewer["id"])
    if snapshot is None:
        raise _not_found()
    return snapshot


@router.get("/bad-cases/{feedback_id}/diagnostics")
def get_bad_case_diagnostics(feedback_id: str, reviewer: QualityReviewer,
                             rt=Depends(get_runtime_dep)) -> dict:
    """Return whitelisted run/retrieval/tool metadata for a negative-feedback run."""
    diagnostics = rt.conversation_store.get_quality_diagnostics(feedback_id)
    if diagnostics is None:
        raise _not_found()
    return diagnostics
