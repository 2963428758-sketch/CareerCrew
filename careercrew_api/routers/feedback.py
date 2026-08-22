"""Authenticated user feedback APIs; snapshot access is deliberately not exposed here."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, model_validator

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_core.conversation.store import OwnershipError

router = APIRouter()

_NEGATIVE_REASONS = {
    "incorrect", "not_relevant", "incomplete", "too_verbose", "unclear",
    "instruction_failure", "tool_failure", "citation_failure", "other",
}


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rating: Literal["positive", "negative"]
    reason: str | None = None
    comment: str | None = None
    share_context: bool = False

    @model_validator(mode="after")
    def validate_reason(self) -> FeedbackRequest:
        if self.rating == "negative" and self.reason not in _NEGATIVE_REASONS:
            raise ValueError("负面反馈必须选择有效原因")
        if self.rating == "positive" and self.reason is not None:
            raise ValueError("正面反馈不能包含负面原因")
        return self


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="消息不存在或不可反馈")


@router.put("/messages/{message_id}/feedback")
def put_feedback(message_id: str, req: FeedbackRequest, current_user: CurrentUser,
                 rt=Depends(get_runtime_dep)) -> dict:
    rt._ensure_heavy()
    try:
        feedback = rt.conversation_store.put_feedback(
            current_user["id"], message_id, rating=req.rating, reason=req.reason,
            comment=req.comment, share_context=req.share_context,
        )
    except OwnershipError as exc:
        raise _not_found() from exc
    return {
        "id": feedback["id"], "message_id": feedback["message_id"], "rating": feedback["rating"],
        "reason": feedback.get("reason"), "comment": feedback.get("comment"),
        "share_context": feedback["share_context"], "updated_at": feedback["updated_at"],
    }


@router.delete("/messages/{message_id}/feedback")
def delete_feedback(message_id: str, current_user: CurrentUser,
                    rt=Depends(get_runtime_dep)) -> dict:
    rt._ensure_heavy()
    try:
        deleted = rt.conversation_store.delete_feedback(current_user["id"], message_id)
    except OwnershipError as exc:
        raise _not_found() from exc
    return {"deleted": deleted, "message_id": message_id}


@router.get("/threads/{thread_id}/feedback")
def list_feedback(thread_id: str, current_user: CurrentUser,
                  rt=Depends(get_runtime_dep)) -> list[dict]:
    rt._ensure_heavy()
    try:
        feedback = rt.conversation_store.list_feedback(current_user["id"], thread_id)
    except OwnershipError as exc:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除") from exc
    return [
        {
            "id": row["id"], "message_id": row["message_id"], "rating": row["rating"],
            "reason": row.get("reason"), "comment": row.get("comment"),
            "share_context": row["share_context"], "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in feedback
    ]
