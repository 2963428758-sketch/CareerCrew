
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from careercrew_api.runtime.common import (
    RegenerateConflictError,
    ResourceNotFoundError,
    _cap_sources,
    _capture_langsmith_run_id,
    _norm_path,
    _observability_from_result,
    _rag_query_retrievals,
    _read_image_paths,
)
from careercrew_core.tracing.langsmith import (
    attach_run_metadata,
    traced_call,
)

if TYPE_CHECKING:

    from careercrew_api.chat_lifecycle import StreamResult


pass




class RegenerateMixin:
    """重新生成：校验/分派/流式实现。"""

    def run_regenerate_stream(self, message_id: str, user_id: str,
                              cb: Callable[[str], None] | None = None,
                              cancel_check: Callable[[], None] | None = None) -> StreamResult:
        """重新生成线程最后一条完整 assistant 消息（复用 turn，新 run + 新 message）。

        校验矩阵（失败映射 404/409，见路由）：
        - 非本人 / 不存在 → ResourceNotFoundError（404）
        - role != assistant / status != completed / 非版本链最新者 → RegenerateConflictError（409）
        - module ∈ consult / interview → RegenerateConflictError（第一版不支持，409）

        稳定 ID：turn_id 不变；run_id / assistant_message_id 变；
        新 message 的 regenerated_from_message_id = 旧 message id（版本链追加）。
        module/agent_id/model/prompt_version/agent_version 从旧 run 行复用，保证可比性。
        """
        return traced_call(
            self._run_regenerate_stream_impl,
            name="careercrew.regenerate",
            run_type="chain",
            run_metadata={"endpoint": "regenerate"},
            message_id=message_id,
            user_id=user_id,
            cb=cb,
            cancel_check=cancel_check,
        )

    def _run_regenerate_stream_impl(self, message_id: str, user_id: str,
                                    cb: Callable[[str], None] | None = None,
                                    cancel_check: Callable[[], None] | None = None) -> StreamResult:
        from careercrew_api.chat_lifecycle import StreamResult, begin_regeneration

        store = self.conversation_store
        self._ensure_heavy()

        msg, thread_id, turn_id, old_run, module, user_msg = self.validate_regenerate(
            message_id, user_id
        )
        ctx = begin_regeneration(
            store, thread_id=thread_id, turn_id=turn_id, user_id=user_id,
            module=module or "chat",
            agent_id=(old_run or {}).get("agent_id") or "unversioned",
            model=(old_run or {}).get("model") or self._conversation_model(),
            regenerated_from_message_id=message_id,
            prompt_version=(old_run or {}).get("prompt_version") or "unversioned",
            agent_version=(old_run or {}).get("agent_version") or "unversioned",
        )

        attach_run_metadata(user_id=user_id, thread_id=thread_id, stage="regenerate")
        ls_run_id = _capture_langsmith_run_id()
        if cancel_check:
            cancel_check()

        # ── 6. 按 module 分派 agent 重跑 ──
        content = ""
        sources: list[dict] = []
        try:
            content, sources, obs = self._dispatch_regenerate(
                module, thread_id, user_id, user_msg, cb, cancel_check
            )
        except Exception as e:
            self._fail_chat_turn(ctx, e)
            raise
        if cancel_check:
            cancel_check()

        metadata = {"sources": sources} if sources else None
        self._finish_chat_turn(
            ctx, content, metadata=metadata,
            langsmith_run_id=ls_run_id,
            input_tokens=obs["input_tokens"], output_tokens=obs["output_tokens"],
            total_tokens=obs["total_tokens"], retrievals=obs["retrievals"],
            tool_calls=obs["tool_calls"],
        )
        if cancel_check:
            cancel_check()
        return StreamResult(content=content, sources=sources, turn=ctx)

    def validate_regenerate(self, message_id: str, user_id: str):
        """regenerate 前置校验（供路由同步 404/409 映射与 run 复用）。

        返回 (msg, thread_id, turn_id, old_run, module, user_msg)；
        失败抛 ResourceNotFoundError（404）或 RegenerateConflictError（409）。
        """
        store = self.conversation_store
        self._ensure_heavy()

        msg = store.get_message(user_id, message_id)
        if msg is None:
            raise ResourceNotFoundError(f"message {message_id} not found")
        if msg.get("role") != "assistant":
            raise RegenerateConflictError("只能重新生成 assistant 消息")
        if msg.get("status") != "completed":
            raise RegenerateConflictError("只能重新生成已完成（completed）的消息")
        if msg.get("deleted_at"):
            raise RegenerateConflictError("该消息已删除，不可重新生成")

        thread_id = msg["thread_id"]
        turn_id = msg["turn_id"]

        old_run = store.get_run(user_id, msg.get("run_id") or "") if msg.get("run_id") else None
        module = (old_run or {}).get("module") or ""
        if module in ("consult", "interview"):
            raise RegenerateConflictError(
                f"「{module}」模块暂不支持重新生成（第一版仅支持 matcher/resume/chat/knowledge）"
            )

        if not self._is_latest_assistant_version(store, user_id, thread_id, turn_id, message_id):
            raise RegenerateConflictError(
                "只能重新生成当前 turn 的最新 assistant 消息（旧版本不可重新生成）"
            )

        # §19：regenerate 仅限线程最后一条完整 assistant 消息。除版本链最新判定外，
        # 追加线程级判定：不允许存在更晚 turn（更大 sequence_no）或同一 turn 更晚
        # created_at 的其他 assistant 消息。
        if not self._is_last_assistant_in_thread(store, user_id, thread_id, turn_id, message_id):
            raise RegenerateConflictError(
                "只能重新生成线程最后一条 assistant 消息（后续轮次已存在）"
            )

        msgs = store.list_messages(thread_id, user_id)
        user_msg = next(
            (m for m in msgs if m["turn_id"] == turn_id and m["role"] == "user"), None
        )
        if user_msg is None:
            raise RegenerateConflictError("该 turn 缺少用户消息，无法重跑")

        return msg, thread_id, turn_id, old_run, module, user_msg

    def _is_latest_assistant_version(self, store, user_id, thread_id, turn_id, message_id) -> bool:
        """判定 message_id 是否为该 turn 版本链的最新 assistant（无后继指向它）。"""
        msgs = store.list_messages(thread_id, user_id)
        for m in msgs:
            if m["turn_id"] == turn_id and m["role"] == "assistant" \
                    and m.get("regenerated_from_message_id") == message_id:
                return False
        return True

    def _is_last_assistant_in_thread(self, store, user_id, thread_id, turn_id, message_id) -> bool:
        """判定 message_id 是否为线程级最后一条 assistant 消息。

        以 turn 的 sequence_no 为主序、消息 created_at 为次序：任何其他 assistant
        消息若处于更晚 turn（sequence_no 更大）或同一 turn 但 created_at 更晚，
        都视为“存在后续消息”，message_id 即非最后一条。
        """
        my_turn = store.get_turn(user_id, turn_id)
        my_seq = (my_turn or {}).get("sequence_no", 0)
        my_created = self._msg_created_at_ts(store, user_id, message_id)
        for m in store.list_messages(thread_id, user_id):
            if m["id"] == message_id or m["role"] != "assistant":
                continue
            t = store.get_turn(user_id, m["turn_id"])
            seq = (t or {}).get("sequence_no", 0)
            created = self._msg_created_at_ts(store, user_id, m["id"])
            if seq > my_seq or (seq == my_seq and created > my_created):
                return False
        return True

    @staticmethod
    def _msg_created_at_ts(store, user_id, message_id) -> str:
        msg = store.get_message(user_id, message_id)
        return (msg or {}).get("created_at") or ""

    def _dispatch_regenerate(self, module: str, thread_id: str, user_id: str,
                             user_msg: dict, cb, cancel_check):
        """按 module 重跑 agent，返回 (content, sources, obs)。"""
        question = user_msg["content"]
        meta = user_msg.get("metadata") or {}
        ep = self._get_episodic(thread_id, user_id)

        if module == "matcher":
            cycle = self.get_cycle(thread_id, user_id)
            cycle.job_matcher = self.new_job_matcher(cb, episodic=ep)
            cycle.run_match(question)
            lr = getattr(cycle.job_matcher, "last_result", None)
            content = (getattr(lr, "content", "") or "").strip()
            obs = _observability_from_result(lr)
            obs["retrievals"] = _rag_query_retrievals(lr.tool_call_details if lr else [])
            return content, [], obs

        if module == "resume":
            # 绑定决策：resume 重跑依赖 metadata 里的完整 jd_text 保真重建输入。
            # conversational /chat 路径（legacy 行）没有 jd_text → 无法忠实重跑，
            # 409 拒绝（而非静默退化为截断摘要/提问原文）。
            jd_text = meta.get("jd_text")
            if not jd_text:
                raise RegenerateConflictError(
                    "该消息缺少原始 JD 元数据（jd_text），无法忠实重建输入，请重新发起简历定制"
                )
            cycle = self.get_cycle(thread_id, user_id)
            cycle.resume_advisor = self.new_resume_advisor(cb, episodic=ep)
            cycle.run_resume(jd_text)
            lr = getattr(cycle.resume_advisor, "last_result", None)
            content = (getattr(lr, "content", "") or "").strip()
            obs = _observability_from_result(lr)
            obs["retrievals"] = _rag_query_retrievals(lr.tool_call_details if lr else [])
            return content, [], obs

        if module == "chat":
            from langchain_core.messages import HumanMessage

            from careercrew_api.attachment_context import build_user_message

            mentions = meta.get("mentions") or []
            attachments = meta.get("attachments") or []
            forced_doc_ids = [
                str(m.get("id") or "") for m in mentions
                if m.get("type") == "knowledge_document" and m.get("id")
            ]
            agent = self.new_career_planner(
                cb, episodic=ep, forced_doc_ids=forced_doc_ids or None,
            )
            state = {
                "thread_id": thread_id, "user_id": user_id, "stage": "planning",
                "user_intent": question,
                "messages": [HumanMessage(content=build_user_message(
                    question, attachments + self._mention_blocks(user_id, mentions)
                ))],
                "pending_action": None, "agent_outputs": {}, "target_companies": [],
            }
            agent.run(state)
            lr = agent.last_result
            content = (getattr(lr, "content", "") or "").strip() if lr else ""
            obs = _observability_from_result(lr)
            obs["retrievals"] = _rag_query_retrievals(lr.tool_call_details if lr else [])
            return content, [], obs

        if module == "knowledge":
            from langchain_core.messages import HumanMessage

            from careercrew_api.attachment_context import build_user_message

            category = meta.get("category") or ""
            scope = meta.get("scope") or "all"
            mentions = meta.get("mentions") or []
            attachments = meta.get("attachments") or []
            # 绑定决策：category/scope 缺失时回退到端点自身默认值（""/"all"），
            # 这仍是忠实重跑（等价于首次无参调用），但记录警告便于排查 legacy 行。
            if not meta.get("category") or not meta.get("scope"):
                import logging
                logging.getLogger(__name__).warning(
                    "regenerate: knowledge turn %s missing category/scope metadata, "
                    "falling back to endpoint defaults (category=%r scope=%r)",
                    user_msg.get("turn_id"), category, scope,
                )
            forced_doc_ids: list[str] = [
                str(m.get("id") or "") for m in mentions
                if m.get("type") == "knowledge_document" and m.get("id")
            ]
            sources: list[dict] = []
            seen: set[str] = set()

            def _sink(r):
                if cancel_check:
                    cancel_check()
                if r.id in seen:
                    return
                seen.add(r.id)
                sources.append({
                    "doc": str(r.metadata.get("doc", "")),
                    "title": str(r.metadata.get("title") or r.metadata.get("doc_name") or ""),
                    "doc_name": str(r.metadata.get("doc_name") or r.metadata.get("title") or ""),
                    "source": str(r.metadata.get("source", "")),
                    "score": round(float(r.score), 3),
                    "text": r.text,
                    "image_path": r.image_path or "",
                    "page": r.page,
                    "category": str(r.metadata.get("category", "")),
                })

            agent = self.new_knowledge_advisor(
                cb, episodic=ep, rag_sink=_sink, category=category,
                knowledge_access_filters=self._knowledge_scope_filters(user_id, scope),
                forced_doc_ids=forced_doc_ids or None,
            )
            state = {
                "thread_id": thread_id, "user_id": user_id, "stage": "knowledge",
                "user_intent": question,
                "messages": [HumanMessage(content=build_user_message(
                    question, attachments + self._mention_blocks(user_id, mentions)
                ))],
                "pending_action": None, "agent_outputs": {}, "target_companies": [],
            }
            agent.run(state)
            lr = agent.last_result
            content = (getattr(lr, "content", "") or "").strip()
            capped = _cap_sources(
                sources, limit=3, min_score=0.0,
                keep_paths=_read_image_paths(lr),
            )
            # 观测检索行（与首次路径一致）
            capped_docs = {_norm_path(s.get("image_path") or "") or s.get("source"): s for s in capped}
            retrievals = []
            for i, s in enumerate(sources):
                key = _norm_path(s.get("image_path") or "") or s.get("source")
                retrievals.append({
                    "query_index": i,
                    "query_text_redacted": question,
                    "scope": scope,
                    "document_id": str(s.get("doc") or "") or None,
                    "chunk_id": None,
                    "recall_score": float(s.get("score") or 0.0),
                    "used_in_final_context": key in capped_docs,
                    # 重跑无强制上下文（mentions 未透传），检索均为自动 'auto'。
                    "retrieval_source": "auto",
                })
            obs = _observability_from_result(lr)
            obs["retrievals"] = retrievals
            return content, capped, obs

        raise RegenerateConflictError(
            f"「{module}」模块暂不支持重新生成（第一版仅支持 matcher/resume/chat/knowledge）"
        )
