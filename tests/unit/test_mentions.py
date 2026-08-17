"""T3.4 mentions 校验纯函数单测（§15.2）。

validate/resolve：knowledge_document 按 owner/visibility 校验；resume 本人所有；
不合法 → MentionRejected（语义=拒绝）。不触碰重组件。
"""
from __future__ import annotations

import pytest

from careercrew_api.mentions import (
    MentionRejected,
    ResolvedMention,
    resolve_mentions,
)


def _doc(doc_id: str, owner: str, visibility: str = "private") -> dict:
    return {"doc": doc_id, "owner_user_id": owner, "visibility": visibility,
            "source": f"{doc_id}.md", "points": 1}


def test_resolves_own_private_knowledge_doc() -> None:
    docs = [_doc("note-a", "u_1"), _doc("note-b", "u_1")]
    resolved = resolve_mentions(
        "u_1", [{"type": "knowledge_document", "id": "note-a"}],
        knowledge_docs=docs, resume_items=[],
    )
    assert len(resolved) == 1
    assert resolved[0] == ResolvedMention(
        type="knowledge_document", id="note-a", name="note-a", visibility="private",
    )


def test_resolves_public_doc_from_other_owner() -> None:
    docs = [_doc("shared", "u_2", visibility="public")]
    resolved = resolve_mentions(
        "u_1", [{"type": "knowledge_document", "id": "shared"}],
        knowledge_docs=docs, resume_items=[],
    )
    assert resolved[0].id == "shared"
    assert resolved[0].visibility == "public"


def test_rejects_other_users_private_doc() -> None:
    docs = [_doc("secret", "u_2", visibility="private")]
    with pytest.raises(MentionRejected):
        resolve_mentions(
            "u_1", [{"type": "knowledge_document", "id": "secret"}],
            knowledge_docs=docs, resume_items=[],
        )


def test_rejects_unknown_knowledge_doc() -> None:
    docs = [_doc("note-a", "u_1")]
    with pytest.raises(MentionRejected):
        resolve_mentions(
            "u_1", [{"type": "knowledge_document", "id": "ghost"}],
            knowledge_docs=docs, resume_items=[],
        )


def test_rejects_forged_public_visibility() -> None:
    """伪造 public：客户端提交的 id 落点本身是他人 private → 拒绝（服务端按真实 owner 判定）。"""
    docs = [_doc("note-a", "u_2", visibility="private")]
    with pytest.raises(MentionRejected):
        resolve_mentions(
            "u_1", [{"type": "knowledge_document", "id": "note-a"}],
            knowledge_docs=docs, resume_items=[],
        )


def test_resolves_resume_mention() -> None:
    resumes = [{"resume_id": "abc123", "filename": "李雷.pdf", "user_id": "u_1"}]
    resolved = resolve_mentions(
        "u_1", [{"type": "resume", "id": "abc123"}],
        knowledge_docs=[], resume_items=resumes,
    )
    assert resolved[0].type == "resume"
    assert resolved[0].name == "李雷.pdf"


def test_rejects_other_users_resume() -> None:
    resumes = [{"resume_id": "abc123", "filename": "李雷.pdf", "user_id": "u_2"}]
    with pytest.raises(MentionRejected):
        resolve_mentions(
            "u_1", [{"type": "resume", "id": "abc123"}],
            knowledge_docs=[], resume_items=resumes,
        )


def test_rejects_unsupported_type() -> None:
    with pytest.raises(MentionRejected):
        resolve_mentions(
            "u_1", [{"type": "agent", "id": "x"}],
            knowledge_docs=[], resume_items=[],
        )


def test_rejects_missing_id() -> None:
    with pytest.raises(MentionRejected):
        resolve_mentions(
            "u_1", [{"type": "knowledge_document", "id": ""}],
            knowledge_docs=[], resume_items=[],
        )


def test_empty_mentions_returns_empty() -> None:
    assert resolve_mentions("u_1", [], knowledge_docs=[], resume_items=[]) == []
