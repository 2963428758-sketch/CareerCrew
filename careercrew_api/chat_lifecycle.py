"""对话 run 生命周期辅助（Phase 1）：把一次流式请求落到 conversation 表的
turn / user message / assistant message / run 四件套，并在流结束后回写状态。

六个流式入口（match / resume / plan / knowledge.ask / consult / interview）共用此
begin/finish/fail/cancel 单一路径，保持 DRY；episodic 双写（record_user_message /
record_thread_messages）在 runtime 层继续保留不动。

命名约定：
- module 对齐 episodic module：matcher / resume / chat / knowledge / consult / interview
- agent_id 对齐 careercrew_core.agents：job_matcher / resume_advisor / career_planner /
  knowledge_advisor / consult_orchestrator / interviewer
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from careercrew_core.conversation.store import ConversationStore


@dataclass
class StreamResult:
    """知识库等返回额外结构化字段的流式结果（content + sources + turn ctx）。"""

    content: str
    sources: list[dict] = field(default_factory=list)
    turn: TurnContext | None = None


@dataclass
class TurnContext:
    """一次 run 的稳定 ID 集（§2.2 / §2.3 / §9）。"""

    thread_id: str          # conversation UUID
    legacy_thread_id: str | None
    turn_id: str
    user_message_id: str
    assistant_message_id: str
    run_id: str
    module: str
    agent_id: str
    model: str
    prompt_version: str = "unversioned"
    agent_version: str = "unversioned"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: str = ""

    def latency_ms(self) -> int:
        return int((datetime.now(timezone.utc) - self.started_at).total_seconds() * 1000)

    def done_fields(self, status: str = "completed") -> dict:
        """组装 §9 done 事件字段（content 之外的部分）。"""
        out: dict = {
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "message_id": self.assistant_message_id,
            "run_id": self.run_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "agent_version": self.agent_version,
            "status": status,
        }
        if self.legacy_thread_id is not None:
            out["legacy_thread_id"] = self.legacy_thread_id
        return out


def begin_turn(
    store: ConversationStore,
    *,
    thread_id: str,
    user_id: str,
    module: str,
    agent_id: str,
    user_text: str,
    model: str,
    title: str | None = None,
) -> TurnContext:
    """开启一轮对话：ensure_conversation → next_turn → user message(completed)
    → assistant message(streaming) → start_run(streaming)，返回稳定 ID 上下文。"""
    conv = store.ensure_conversation(
        thread_id, user_id, module, title=title, retrieval_scope=None
    )
    turn = store.next_turn(thread_id, user_id)
    user_msg = store.add_user_message(
        turn["id"], turn["thread_id"], user_id, user_text, "completed"
    )
    asst_msg = store.add_assistant_message(
        turn["id"], turn["thread_id"], user_id, "", None, None
    )
    store.set_message_status(user_id, asst_msg["id"], "streaming")
    # 先落 assistant message（run_id 暂 NULL），start_run 时把 run 关联到该 message，
    # 并把消息行的 run_id 回填为真实 run_id（见下）。
    run = store.start_run(
        thread_id=conv["id"], turn_id=turn["id"], message_id=asst_msg["id"],
        user_id=user_id, module=module, agent_id=agent_id, model=model,
        prompt_version="unversioned", agent_version="unversioned",
        status="streaming",
    )
    store.set_message_run_id(user_id, asst_msg["id"], run["id"])

    return TurnContext(
        thread_id=conv["id"],
        legacy_thread_id=conv.get("legacy_thread_id"),
        turn_id=turn["id"],
        user_message_id=user_msg["id"],
        assistant_message_id=asst_msg["id"],
        run_id=run["id"],
        module=module,
        agent_id=agent_id,
        model=model,
        user_id=user_id,
    )


def finish_turn(
    store: ConversationStore, ctx: TurnContext, content: str, status: str = "completed",
    metadata: dict | None = None,
) -> None:
    """流结束：写 assistant message 内容 + 状态（+ 可选 metadata 富结构），并收尾 run。"""
    store.set_message_content(
        ctx.user_id, ctx.assistant_message_id, content, status=status, metadata=metadata
    )
    store.finish_run(
        ctx.user_id, ctx.run_id, status=status, latency_ms=ctx.latency_ms()
    )


def fail_turn(store: ConversationStore, ctx: TurnContext, exc: BaseException) -> None:
    """异常：mark message/run failed（记录 error_type / error_summary）。"""
    error_type = type(exc).__name__ or "Error"
    summary = _truncate(str(exc))
    store.set_message_content(ctx.user_id, ctx.assistant_message_id, "", status="failed")
    store.finish_run(
        ctx.user_id, ctx.run_id, status="failed",
        latency_ms=ctx.latency_ms(),
        error_type=error_type,
        error_summary=summary,
    )


def cancel_turn(store: ConversationStore, ctx: TurnContext) -> None:
    """协作式取消：mark message/run cancelled。"""
    store.set_message_content(ctx.user_id, ctx.assistant_message_id, "", status="cancelled")
    store.finish_run(ctx.user_id, ctx.run_id, status="cancelled", latency_ms=ctx.latency_ms())


def _truncate(text: str, limit: int = 500) -> str:
    return text if len(text) <= limit else text[:limit] + "…"
