from __future__ import annotations

from careercrew_core.conversation.db import FakeConversationDb
from careercrew_core.conversation.store import ConversationStore
from careercrew_core.workspace.consultation import ConsultationWorkspace


def _seed() -> tuple[ConversationStore, str]:
    store = ConversationStore(FakeConversationDb())
    store.ensure_conversation("consult-thread", "alice", "consult", title="会诊")
    turn = store.next_turn("consult-thread", "alice")
    store.add_user_message(turn["id"], "consult-thread", "alice", "是否转向 AI 岗位？", "completed")
    answer = store.add_assistant_message(
        turn["id"], "consult-thread", "alice", "", None, None
    )
    store.set_message_content(
        "alice",
        answer["id"],
        "综合建议：先补齐项目证据。",
        metadata={
            "opinions": {
                "career_planner": "建议先补齐项目证据，再投递 AI 岗位",
                "salary_negotiator": "建议先补齐项目证据，同时保留谈薪空间",
                "risk_reviewer": "投递前注意项目证据不足的风险",
            },
            "calls": [{
                "agent": "salary_negotiator", "name": "salary_query",
                "status": "completed", "args": {"company": "secret"},
                "tool_call_details": [{"args": {"secret": "must-not-leak"}}],
            }],
        },
    )
    return store, answer["id"]


def test_report_extracts_consensus_disagreement_evidence_without_tool_args() -> None:
    store, message_id = _seed()
    service = ConsultationWorkspace(store)

    report = service.build_report("alice", message_id)
    assert report["source_message_id"] == message_id
    assert report["consensus"]
    assert report["alternatives"]
    assert report["risks"]
    assert any(item["agent"] == "salary_negotiator" for item in report["evidence"])
    serialized = str(report)
    assert "secret" not in serialized
    assert "tool_call_details" not in serialized


def test_report_and_plan_use_explicit_confirm_and_optimistic_version() -> None:
    store, message_id = _seed()
    service = ConsultationWorkspace(store)
    draft = service.save_report("alice", message_id)
    assert draft["status"] == "draft"

    plan = service.create_plan(
        "alice", draft["id"], title="AI 岗位准备", steps=[{"title": "补项目证据"}]
    )
    assert plan["status"] == "draft"
    confirmed = service.update_plan("alice", plan["id"], status="confirmed", version=1)
    assert confirmed["status"] == "confirmed"

    try:
        service.update_plan("alice", plan["id"], status="draft", version=1)
    except ValueError as exc:
        assert "版本" in str(exc)
    else:
        raise AssertionError("stale plan update must be rejected")

    assert service.update_report("bob", draft["id"], status="confirmed", version=1) is None
