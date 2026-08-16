"""ConversationStore 领域服务：对话核心存储的业务编排。

不直接写 SQL，全部通过 ConversationDb 契约；所有带 user_id 的方法先校验
所有权，不匹配抛 OwnershipError。方法集对齐 T1.1 brief 的绑定决策，
供 T1.2（streaming 接线）与 T1.6（feedback/eval）调用。

UUIDv7 生成 id；legacy `t-${Date.now()}` 线程 ID 通过 conversations.legacy_thread_id
映射到 UUID（现状前端兼容）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID
from typing import Any

from careercrew_core.conversation.db import (
    ConversationDb,
    SequenceCollision,
    _now,
)
from careercrew_core.conversation.uuid7 import uuid7
from careercrew_core.feedback.snapshots import build_snapshot


class OwnershipError(Exception):
    """资源不属于该用户（user_id 不匹配）时抛出。"""


def _is_uuid(value: Any) -> bool:
    if isinstance(value, UUID):
        return True
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


class ConversationStore:
    def __init__(self, db: ConversationDb) -> None:
        self._db = db

    # ── helpers ──

    def _require_conversation(self, thread_id: str, user_id: str) -> dict | None:
        """按 UUID 或 legacy id 解析会话，校验所有权。

        存在且属于该用户 → 返回会话行；存在但属于他人 → OwnershipError；
        不存在 → None。
        """
        if _is_uuid(thread_id):
            conv = self._db.get_conversation(user_id, thread_id)
            if conv is not None:
                return conv
            if self._db.conversation_exists(thread_id):
                raise OwnershipError(
                    f"conversation {thread_id!r} 不属于用户 {user_id!r}"
                )
            return None
        conv = self._db.get_conversation_by_legacy(user_id, thread_id)
        if conv is not None:
            return conv
        if self._db.legacy_exists(thread_id):
            raise OwnershipError(
                f"conversation (legacy) {thread_id!r} 不属于用户 {user_id!r}"
            )
        return None

    def _require_owned(self, thread_id: str, user_id: str) -> dict:
        conv = self._require_conversation(thread_id, user_id)
        if conv is None:
            # 不存在也按所有权拒绝：不泄露资源是否存在
            raise OwnershipError(f"conversation {thread_id!r} 不存在或不属于用户 {user_id!r}")
        return conv

    # ── conversations ──

    def ensure_conversation(
        self,
        thread_id: str,
        user_id: str,
        module: str,
        title: str | None = None,
        retrieval_scope: dict | None = None,
    ) -> dict:
        """幂等创建/复用会话。thread_id 为 UUID 直接用；否则走 legacy 映射。

        返回会话行（含 id=UUID、legacy_thread_id）。
        """
        if _is_uuid(thread_id):
            conversation_id = thread_id
            legacy = None
            conv = self._db.get_conversation(user_id, conversation_id)
            if conv is not None:
                return conv
        else:
            legacy = thread_id
            conv = self._db.get_conversation_by_legacy(user_id, legacy)
            if conv is not None:
                return conv
            conversation_id = str(uuid7())

        return self._db.upsert_conversation(
            conversation_id, user_id, module, title, legacy, retrieval_scope
        )

    def get_conversation(self, thread_id: str, user_id: str) -> dict | None:
        """按 UUID 或 legacy id 查会话。

        存在但属于其他用户 → OwnershipError；不存在 → None。
        """
        return self._require_conversation(thread_id, user_id)

    # ── turns ──

    def next_turn(self, thread_id: str, user_id: str) -> dict:
        """为会话分配下一个 turn（sequence_no = MAX+1，UNIQUE 冲突重试一次）。"""
        conv = self._require_owned(thread_id, user_id)
        seq = self._db.max_sequence_no(user_id, conv["id"]) + 1
        turn_id = str(uuid7())
        try:
            return self._db.insert_turn(turn_id, conv["id"], user_id, seq)
        except SequenceCollision:
            # UNIQUE(thread_id, sequence_no) 冲突：重试一次（并发 MAX+1 撞车）
            seq = self._db.max_sequence_no(user_id, conv["id"]) + 1
            turn_id = str(uuid7())
            return self._db.insert_turn(turn_id, conv["id"], user_id, seq)

    def get_turn(self, user_id: str, turn_id: str) -> dict | None:
        """按 user_id 取 turn 行（含 sequence_no）；不存在 / 所有权不匹配返回 None。"""
        return self._db.get_turn(user_id, turn_id)

    # ── messages ──

    def add_user_message(
        self, turn_id: str, thread_id: str, user_id: str, content: str, status: str,
        metadata: dict | None = None,
    ) -> dict:
        conv = self._require_owned(thread_id, user_id)
        msg_id = str(uuid7())
        return self._db.insert_message(
            msg_id, conv["id"], turn_id, user_id, "user", content, None, None,
            status, metadata,
        )

    def add_assistant_message(
        self,
        turn_id: str,
        thread_id: str,
        user_id: str,
        content: str,
        run_id: str | None,
        regenerated_from_message_id: str | None,
    ) -> dict:
        conv = self._require_owned(thread_id, user_id)
        msg_id = str(uuid7())
        return self._db.insert_message(
            msg_id, conv["id"], turn_id, user_id, "assistant", content,
            run_id, regenerated_from_message_id, "pending",
        )

    def set_message_status(self, user_id: str, message_id: str, status: str) -> dict:
        """按 user_id + message_id 更新状态；所有权不匹配抛 OwnershipError，
        找不到时返回 {}。"""
        if self._db.get_message(user_id, message_id) is None:
            raise OwnershipError(
                f"message {message_id!r} 不属于或不存在于用户 {user_id!r}"
            )
        return self._db.update_message_status(user_id, message_id, status)

    def set_message_content(
        self, user_id: str, message_id: str, content: str, status: str = "completed",
        metadata: dict | None = None,
    ) -> dict:
        """流式结束写入 assistant 消息最终内容，并同步更新状态与 completed_at。

        metadata（assistant 富结构，如 sources/opinions）可选：None=不动。所有权
        不匹配抛 OwnershipError，找不到返回 {}。
        """
        if self._db.get_message(user_id, message_id) is None:
            raise OwnershipError(
                f"message {message_id!r} 不属于或不存在于用户 {user_id!r}"
            )
        return self._db.update_message_content(user_id, message_id, content, status, metadata)

    def set_message_run_id(self, user_id: str, message_id: str, run_id: str) -> dict:
        """回填 assistant message 的 run_id（message 先于 run 创建，run 生成后再关联）。

        所有权不匹配抛 OwnershipError，找不到返回 {}。
        """
        if self._db.get_message(user_id, message_id) is None:
            raise OwnershipError(
                f"message {message_id!r} 不属于或不存在于用户 {user_id!r}"
            )
        return self._db.update_message_run_id(user_id, message_id, run_id)

    def list_messages(self, thread_id: str, user_id: str) -> list[dict]:
        conv = self._require_owned(thread_id, user_id)
        return self._db.list_messages(user_id, conv["id"])

    # ── rename / clear / delete / list runs ──

    def rename_title(self, thread_id: str, user_id: str, title: str) -> dict:
        """更新会话标题（按 UUID 或 legacy id）；所有权不匹配/不存在抛 OwnershipError。"""
        conv = self._require_owned(thread_id, user_id)
        return self._db.update_title(user_id, conv["id"], title)

    def clear_conversation(self, thread_id: str, user_id: str) -> int:
        """清空会话消息（保留 conversation / title / retrieval_scope）。

        删除该会话全部 turns（级联 messages）与 runs/retrievals/tool_calls；
        返回删除的 turn 数。
        """
        conv = self._require_owned(thread_id, user_id)
        return self._db.clear_conversation(user_id, conv["id"])

    def delete_conversation(self, thread_id: str, user_id: str) -> bool:
        """删除会话行及其全部子表（turns/messages/runs/retrievals/tool_calls）。"""
        conv = self._require_owned(thread_id, user_id)
        return self._db.delete_conversation(user_id, conv["id"])

    def list_runs(self, thread_id: str, user_id: str) -> list[dict]:
        """按会话返回全部 agent_runs（按 created_at 升序）。"""
        conv = self._require_owned(thread_id, user_id)
        return self._db.list_runs(user_id, conv["id"])


    def get_message(self, user_id: str, message_id: str) -> dict | None:
        """按 user_id 取单条消息；不存在 / 所有权不匹配返回 None（跨用户视为不存在）。"""
        return self._db.get_message(user_id, message_id)

    def list_message_versions(self, message_id: str, user_id: str) -> list[dict]:
        """同一 turn 的 assistant 版本链（root -> leaf，沿 regenerated_from 回溯）。"""
        msg = self._db.get_message(user_id, message_id)  # 校验所有权
        if msg is None:
            raise OwnershipError(f"message {message_id!r} 不属于或不存在于用户 {user_id!r}")
        turn_messages = [
            m for m in self._db.list_messages(user_id, msg["thread_id"])
            if m["turn_id"] == msg["turn_id"] and m["role"] == "assistant"
        ]
        by_id = {m["id"]: m for m in turn_messages}
        # 沿链回溯到根，再正向返回
        chain: list[dict] = []
        cur = msg
        seen: set[str] = set()
        while cur and cur["id"] not in seen:
            chain.append(cur)
            seen.add(cur["id"])
            parent = cur.get("regenerated_from_message_id")
            cur = by_id.get(parent) if parent else None
        chain.reverse()
        return chain

    # ── runs ──

    def start_run(
        self,
        thread_id: str,
        turn_id: str,
        message_id: str,
        user_id: str,
        module: str,
        agent_id: str,
        model: str,
        prompt_version: str = "unversioned",
        agent_version: str = "unversioned",
        status: str = "pending",
        effective_tools: list[str] | None = None,
    ) -> dict:
        conv = self._require_owned(thread_id, user_id)
        run_id = str(uuid7())
        return self._db.insert_run(
            run_id, user_id, conv["id"], turn_id, message_id, module, agent_id,
            model, prompt_version, agent_version, status,
            effective_tools=effective_tools,
        )

    def finish_run(
        self,
        user_id: str,
        run_id: str,
        status: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: int | None = None,
        langsmith_run_id: str | None = None,
        error_type: str | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> dict:
        run = self._db.get_run(user_id, run_id)
        if run is None:
            raise OwnershipError(f"run {run_id!r} 不属于或不存在于用户 {user_id!r}")
        fields: dict[str, Any] = {"status": status}
        if status in ("completed", "failed", "cancelled"):
            fields["finished_at"] = _now()
        if input_tokens is not None:
            fields["input_tokens"] = input_tokens
        if output_tokens is not None:
            fields["output_tokens"] = output_tokens
        if total_tokens is not None:
            fields["total_tokens"] = total_tokens
        if latency_ms is not None:
            fields["latency_ms"] = latency_ms
        if langsmith_run_id is not None:
            fields["langsmith_run_id"] = langsmith_run_id
        if error_type is not None:
            fields["error_type"] = error_type
        if error_code is not None:
            fields["error_code"] = error_code
        if error_summary is not None:
            fields["error_summary"] = error_summary
        return self._db.update_run(user_id, run_id, fields)

    def get_run(self, user_id: str, run_id: str) -> dict | None:
        """按 user_id 取 run 行；不存在 / 所有权不匹配返回 None（跨用户视为不存在）。"""
        return self._db.get_run(user_id, run_id)

    # ── feedback / privacy snapshots ──

    def _feedback_target(self, user_id: str, message_id: str) -> dict:
        """Resolve an eligible assistant result without revealing foreign messages."""
        try:
            message_id = str(UUID(message_id))
        except (AttributeError, TypeError, ValueError) as exc:
            raise OwnershipError("feedback target is not available") from exc
        message = self._db.get_message(user_id, message_id)
        if (message is None or message.get("role") != "assistant"
                or message.get("status") != "completed" or not message.get("run_id")):
            raise OwnershipError("feedback target is not available")
        run = self._db.get_run(user_id, message["run_id"])
        if (run is None or run.get("thread_id") != message["thread_id"]
                or run.get("turn_id") != message["turn_id"]
                or run.get("message_id") != message["id"]):
            raise OwnershipError("feedback target is not available")
        return message

    def put_feedback(self, user_id: str, message_id: str, *, rating: str,
                     reason: str | None, comment: str | None, share_context: bool) -> dict:
        """Upsert feedback, deriving every relationship from the owned assistant message."""
        message = self._feedback_target(user_id, message_id)
        snapshot_fields = None
        if rating == "negative" and share_context:
            messages = self._db.list_messages(user_id, message["thread_id"])
            snapshot, count, version = build_snapshot(messages, message)
            snapshot_fields = {
                "id": str(uuid7()), "snapshot_json": snapshot, "redaction_version": version,
                "redaction_count": count,
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat(),
            }
        return self._db.replace_feedback_with_snapshot(user_id, {
            "id": str(uuid7()), "thread_id": message["thread_id"], "turn_id": message["turn_id"],
            "message_id": message["id"], "run_id": message["run_id"], "rating": rating,
            "reason": reason, "comment": comment, "share_context": share_context,
        }, snapshot_fields)

    def list_feedback(self, user_id: str, thread_id: str) -> list[dict]:
        """List the current user's metadata-only feedback for an owned conversation."""
        conv = self._require_owned(thread_id, user_id)
        return self._db.list_feedback(user_id, conv["id"])

    def delete_feedback(self, user_id: str, message_id: str) -> bool:
        """Hard-delete feedback/snapshot and record content-free deletion metadata."""
        message = self._feedback_target(user_id, message_id)
        return self._db.delete_feedback_with_audit(user_id, message["id"], {"deleted": None})

    # ── regeneration idempotency ──

    def get_regeneration(self, user_id: str, key: str) -> str | None:
        """取某 (user_id, key) 首次 regenerate 生成的 message_id；无则 None。"""
        return self._db.get_regeneration(user_id, key)

    def create_regeneration(self, user_id: str, key: str, message_id: str) -> str | None:
        """登记一次 regenerate 的幂等键；已存在返回 None（调用方复用首次结果）。"""
        return self._db.create_regeneration(user_id, key, message_id)

    def reserve_regeneration(self, user_id: str, key: str) -> tuple[str, str | None]:
        """原子预留幂等键（上游预留，杜绝并发同 key 双跑；三态契约）。

        返回 (state, message_id)：
        - (\"reserved\", None)：本次成功预留，应 dispatch。
        - (\"exists\", <message_id>)：已存在且已完成，应 replay 该 message。
        - (\"exists\", None)：已存在但进行中（首个请求未回填），应 409。
        """
        return self._db.reserve_regeneration(user_id, key)

    def complete_regeneration(self, user_id: str, key: str, message_id: str) -> str | None:
        """预留成功后回填最终 message_id。"""
        return self._db.complete_regeneration(user_id, key, message_id)

    def release_regeneration(self, user_id: str, key: str) -> bool:
        """释放未完成的预留（流中途失败不污名化该 key）。"""
        return self._db.release_regeneration(user_id, key)

    # ── retrievals / tool calls ──

    def add_retrieval(
        self,
        user_id: str,
        run_id: str,
        query_index: int,
        query_text_redacted: str | None = None,
        scope: str | None = None,
        document_id: str | None = None,
        chunk_id: str | None = None,
        recall_score: float | None = None,
        rerank_score: float | None = None,
        rank_before: int | None = None,
        rank_after: int | None = None,
        used_in_final_context: bool = False,
        retrieval_source: str = "auto",
    ) -> dict:
        self._require_run_owned(user_id, run_id)
        fields: dict[str, Any] = {
            "used_in_final_context": used_in_final_context,
            "retrieval_source": retrieval_source,
        }
        for key, val in (
            ("query_text_redacted", query_text_redacted),
            ("scope", scope),
            ("document_id", document_id),
            ("chunk_id", chunk_id),
            ("recall_score", recall_score),
            ("rerank_score", rerank_score),
            ("rank_before", rank_before),
            ("rank_after", rank_after),
        ):
            if val is not None:
                fields[key] = val
        return self._db.insert_retrieval(str(uuid7()), run_id, query_index, fields)

    def add_tool_call(
        self,
        user_id: str,
        run_id: str,
        tool_name: str,
        input_redacted: dict | None = None,
        output_summary: str | None = None,
        status: str = "completed",
        duration_ms: int | None = None,
        requires_hitl: bool = False,
        hitl_status: str | None = None,
        error_type: str | None = None,
        error_summary: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict:
        self._require_run_owned(user_id, run_id)
        fields: dict[str, Any] = {
            "status": status,
            "requires_hitl": requires_hitl,
        }
        for key, val in (
            ("input_redacted", input_redacted),
            ("output_summary", output_summary),
            ("duration_ms", duration_ms),
            ("hitl_status", hitl_status),
            ("error_type", error_type),
            ("error_summary", error_summary),
            ("started_at", started_at),
            ("finished_at", finished_at),
        ):
            if val is not None:
                fields[key] = val
        return self._db.insert_tool_call(str(uuid7()), run_id, tool_name, fields)

    def _require_run_owned(self, user_id: str, run_id: str) -> dict:
        run = self._db.get_run(user_id, run_id)
        if run is None:
            raise OwnershipError(f"run {run_id!r} 不属于或不存在于用户 {user_id!r}")
        return run
