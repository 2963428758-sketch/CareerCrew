
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from careercrew_api.runtime.common import (
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
    from careercrew_core.workflow.job_cycle import JobCycle


pass




class StreamingMixin:
    """match/resume/planner/knowledge 四条流式编排。"""

    def get_cycle(self, thread_id: str, user_id: str) -> JobCycle:
        """按 thread_id 取/建 JobCycle（承接 match->resume 跨步骤历史与画像 preamble）。"""
        self._ensure_heavy()
        key = (user_id, thread_id)
        with self._cycles_lock:
            if key in self._cycles:
                self._cycles.move_to_end(key)
                return self._cycles[key]
            from careercrew_core.workflow.job_cycle import JobCycle

            ep = self._get_episodic(thread_id, user_id)
            jm = self.new_job_matcher(episodic=ep)
            ra = self.new_resume_advisor(episodic=ep)
            cycle = JobCycle(
                jm, ra, user_model_store=self.memory_service,
                user_id=user_id, streaming=True, history_loader=self._history_loader,
                thread_id=thread_id,
            )
            self._cycles[key] = cycle
            if len(self._cycles) > self._max_cycles:
                self._cycles.popitem(last=False)  # 逐出最旧
            return cycle

    def run_match_stream(self, thread_id: str, user_id: str, intent: str,
                         cb: Callable[[str], None] | None = None,
                         mentions: list[dict] | None = None,
                         attachments: list[dict] | None = None,
                         cancel_check: Callable[[], None] | None = None,
                         tools: list[str] | None = None) -> StreamResult:
        """流式 match：用带 callback 的 agent 替换 cycle 中的 matcher，保留对话历史。

        返回 StreamResult（content + turn 上下文）；转交 traced_call 透传。
        """
        return traced_call(
            self._run_match_stream_impl,
            name="careercrew.match",
            run_type="chain",
            run_metadata={"endpoint": "match"},
            thread_id=thread_id,
            user_id=user_id,
            intent=intent,
            cb=cb,
            mentions=mentions,
            attachments=attachments,
            cancel_check=cancel_check,
            tools=tools,
        )

    def _run_match_stream_impl(self, thread_id: str, user_id: str, intent: str,
                               cb: Callable[[str], None] | None = None,
                               mentions: list[dict] | None = None,
                               attachments: list[dict] | None = None,
                               cancel_check: Callable[[], None] | None = None,
                               tools: list[str] | None = None) -> StreamResult:
        from careercrew_api.attachment_context import build_user_message
        from careercrew_api.chat_lifecycle import StreamResult

        attachments = attachments or []
        attach_run_metadata(user_id=user_id, thread_id=thread_id, stage="match")
        ls_run_id = _capture_langsmith_run_id()
        if cancel_check:
            cancel_check()
        user_meta: dict | None = None
        if mentions or attachments:
            user_meta = {}
            if mentions:
                user_meta["mentions"] = mentions
            if attachments:
                user_meta["attachments"] = attachments
        effective = self.compute_effective_tools("matcher", tools, user_id=user_id)
        hitl = self._hitl_requires()
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="matcher", agent_id="job_matcher",
            user_text=intent, user_metadata=user_meta, effective_tools=effective,
        )
        cycle = self.get_cycle(thread_id, user_id)
        try:
            # 先落库用户消息：即使后续 agent 运行挂起/失败，问题也不丢
            cycle.pending_user_entry_id = self.record_user_message(
                user_id, thread_id, intent, module="matcher"
            )
        except Exception:
            cycle.pending_user_entry_id = None
        if cancel_check:
            cancel_check()
        ep = self._get_episodic(thread_id, user_id)
        forced_doc_ids = [
            str(m.get("id") or "") for m in (mentions or [])
            if m.get("type") == "knowledge_document" and m.get("id")
        ]
        cycle.job_matcher = self.new_job_matcher(
            cb, episodic=ep, allowed=effective, hitl_requires=hitl,
            forced_doc_ids=forced_doc_ids or None,
        )
        if cancel_check:
            cancel_check()
        composed = build_user_message(intent, attachments + self._mention_blocks(user_id, mentions))
        try:
            result = cycle.run_match(intent, composed=composed)
        except Exception as e:
            self._fail_chat_turn(ctx, e)
            raise
        if cancel_check:
            cancel_check()
        # 超轮次兜底：agent 搜索轮次耗尽时补一段结论，避免以"我再搜一下"截断
        lr = getattr(cycle.job_matcher, "last_result", None)
        if lr is not None and getattr(lr, "stopped_reason", "") == "max_iterations":
            result = result + (
                "\n\n---\n*（搜索轮次已达上限，以上为已找到的匹配岗位。"
                "如需更精准结果，可补充城市/薪资/方向等条件后继续对话。）*"
            )
        try:
            self.record_thread_messages(
                user_id, thread_id, user_text="", agent_text=result,
                module="matcher",
            )
        except Exception:
            pass  # transcript 写入失败不阻塞主流程
        obs = _observability_from_result(lr)
        obs["retrievals"] = _rag_query_retrievals(lr.tool_call_details if lr else [])
        self._finish_chat_turn(
            ctx, result, langsmith_run_id=ls_run_id,
            input_tokens=obs["input_tokens"], output_tokens=obs["output_tokens"],
            total_tokens=obs["total_tokens"], retrievals=obs["retrievals"],
            tool_calls=obs["tool_calls"],
        )
        if cancel_check:
            cancel_check()
        return StreamResult(content=result, turn=ctx)

    def run_resume_stream(self, thread_id: str, user_id: str, jd_text: str,
                          cb: Callable[[str], None] | None = None,
                          mentions: list[dict] | None = None,
                          attachments: list[dict] | None = None,
                          cancel_check: Callable[[], None] | None = None,
                          tools: list[str] | None = None) -> StreamResult:
        """流式 resume：用带 callback 的 agent 替换 cycle 中的 advisor，保留对话历史。"""
        return traced_call(
            self._run_resume_stream_impl,
            name="careercrew.resume",
            run_type="chain",
            run_metadata={"endpoint": "resume"},
            thread_id=thread_id,
            user_id=user_id,
            jd_text=jd_text,
            cb=cb,
            mentions=mentions,
            attachments=attachments,
            cancel_check=cancel_check,
            tools=tools,
        )

    def _run_resume_stream_impl(self, thread_id: str, user_id: str, jd_text: str,
                                cb: Callable[[str], None] | None = None,
                                mentions: list[dict] | None = None,
                                attachments: list[dict] | None = None,
                                cancel_check: Callable[[], None] | None = None,
                                tools: list[str] | None = None) -> StreamResult:
        from careercrew_api.attachment_context import build_user_message
        from careercrew_api.chat_lifecycle import StreamResult

        attachments = attachments or []
        attach_run_metadata(user_id=user_id, thread_id=thread_id, stage="resume")
        ls_run_id = _capture_langsmith_run_id()
        if cancel_check:
            cancel_check()
        user_text = f"按这个 JD 定制简历：{jd_text[:200]}"
        # 注意（绑定的决策，勿改动）：conversation 表用 module="resume"（canonical，
        # 对齐前端模块分类 sidebar/threadStore），而下方 episodic 双写
        # （record_user_message / record_thread_messages）沿用遗留值 module="matcher"。
        # 二者有意不一致，T1.5/T1.6 请勿把 episodic 的 "matcher" 迁移到 conversation。
        user_meta: dict = {"jd_text": jd_text[:5000]}
        if mentions:
            user_meta["mentions"] = mentions
        if attachments:
            user_meta["attachments"] = attachments
        effective = self.compute_effective_tools("resume", tools, user_id=user_id)
        hitl = self._hitl_requires()
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="resume", agent_id="resume_advisor",
            user_text=user_text,
            # T1.6：user content 是截断摘要，完整 jd_text 存 metadata 供 regenerate
            # 忠实重跑（截断至 5000 字符）。
            user_metadata=user_meta,
            effective_tools=effective,
        )
        cycle = self.get_cycle(thread_id, user_id)
        try:
            cycle.pending_user_entry_id = self.record_user_message(
                user_id, thread_id, user_text, module="matcher"
            )
        except Exception:
            cycle.pending_user_entry_id = None
        if cancel_check:
            cancel_check()
        ep = self._get_episodic(thread_id, user_id)
        forced_doc_ids = [
            str(m.get("id") or "") for m in (mentions or [])
            if m.get("type") == "knowledge_document" and m.get("id")
        ]
        cycle.resume_advisor = self.new_resume_advisor(
            cb, episodic=ep, allowed=effective, hitl_requires=hitl,
            forced_doc_ids=forced_doc_ids or None,
        )
        if cancel_check:
            cancel_check()
        composed = build_user_message(
            f"按这个 JD 定制简历：{jd_text}",
            attachments + self._mention_blocks(user_id, mentions),
        )
        try:
            result = cycle.run_resume(jd_text, composed=composed)
        except Exception as e:
            self._fail_chat_turn(ctx, e)
            raise
        if cancel_check:
            cancel_check()
        try:
            self.record_thread_messages(
                user_id, thread_id,
                user_text="",
                agent_text=result,
                module="matcher",
            )
        except Exception:
            pass
        lr = getattr(cycle.resume_advisor, "last_result", None)
        obs = _observability_from_result(lr)
        obs["retrievals"] = _rag_query_retrievals(lr.tool_call_details if lr else [])
        self._finish_chat_turn(
            ctx, result, langsmith_run_id=ls_run_id,
            input_tokens=obs["input_tokens"], output_tokens=obs["output_tokens"],
            total_tokens=obs["total_tokens"], retrievals=obs["retrievals"],
            tool_calls=obs["tool_calls"],
        )
        if cancel_check:
            cancel_check()
        return StreamResult(content=result, turn=ctx)

    def run_planner_chat_stream(self, thread_id: str, user_id: str, intent: str,
                                cb: Callable[[str], None] | None = None,
                                mentions: list[dict] | None = None,
                                attachments: list[dict] | None = None,
                                cancel_check: Callable[[], None] | None = None,
                                tools: list[str] | None = None) -> StreamResult:
        """求职对话：职业规划师主理（聚焦求职规划：画像/目标公司池/阶段规划与复盘）。"""
        return traced_call(
            self._run_planner_chat_stream_impl,
            name="careercrew.plan",
            run_type="chain",
            run_metadata={"endpoint": "plan"},
            thread_id=thread_id,
            user_id=user_id,
            intent=intent,
            cb=cb,
            mentions=mentions,
            attachments=attachments,
            cancel_check=cancel_check,
            tools=tools,
        )

    def _run_planner_chat_stream_impl(self, thread_id: str, user_id: str, intent: str,
                                      cb: Callable[[str], None] | None = None,
                                      mentions: list[dict] | None = None,
                                      attachments: list[dict] | None = None,
                                      cancel_check: Callable[[], None] | None = None,
                                      tools: list[str] | None = None) -> StreamResult:
        from careercrew_api.attachment_context import build_user_message
        from careercrew_api.chat_lifecycle import StreamResult

        attachments = attachments or []
        attach_run_metadata(user_id=user_id, thread_id=thread_id, stage="planning")
        ls_run_id = _capture_langsmith_run_id()
        from langchain_core.messages import HumanMessage

        if cancel_check:
            cancel_check()
        user_meta: dict | None = None
        if mentions or attachments:
            user_meta = {}
            if mentions:
                user_meta["mentions"] = mentions
            if attachments:
                user_meta["attachments"] = attachments
        from careercrew_core.tools.effective import planner_tools_for_intent

        effective = planner_tools_for_intent(
            intent,
            self.compute_effective_tools("chat", tools, user_id=user_id),
        )
        hitl = self._hitl_requires()
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="chat", agent_id="career_planner",
            user_text=intent, user_metadata=user_meta, effective_tools=effective,
        )
        ep = self._get_episodic(thread_id, user_id)
        forced_doc_ids = [
            str(m.get("id") or "") for m in (mentions or [])
            if m.get("type") == "knowledge_document" and m.get("id")
        ]
        agent = self.new_career_planner(
            cb, episodic=ep, allowed=effective, hitl_requires=hitl,
            forced_doc_ids=forced_doc_ids or None,
        )
        try:
            # 先落库用户消息：长工具链（搜岗位/查薪资）中断也不丢问题
            pending_id = self.record_user_message(
                user_id, thread_id, intent, module="chat"
            )
        except Exception:
            pending_id = None
        if cancel_check:
            cancel_check()
        composed = build_user_message(intent, attachments + self._mention_blocks(user_id, mentions))
        state = {
            "thread_id": thread_id, "user_id": user_id, "stage": "planning",
            "user_intent": intent,
            "messages": [HumanMessage(content=composed)],
            "pending_action": None, "agent_outputs": {}, "target_companies": [],
            "pending_user_entry_id": pending_id,
        }
        if cancel_check:
            cancel_check()
        try:
            agent.run(state)
        except Exception as e:
            self._fail_chat_turn(ctx, e)
            raise
        if cancel_check:
            cancel_check()
        result = (agent.last_result.content or "").strip() if agent.last_result else ""
        if not result:
            result = "（本轮未产出完整规划，可补充方向/技能/城市/薪资等信息后继续对话）"
        try:
            self.record_thread_messages(
                user_id, thread_id, user_text="", agent_text=result, module="chat",
            )
        except Exception:
            pass  # transcript 写入失败不阻塞主流程
        lr = agent.last_result
        obs = _observability_from_result(lr)
        obs["retrievals"] = _rag_query_retrievals(lr.tool_call_details if lr else [])
        self._finish_chat_turn(
            ctx, result, langsmith_run_id=ls_run_id,
            input_tokens=obs["input_tokens"], output_tokens=obs["output_tokens"],
            total_tokens=obs["total_tokens"], retrievals=obs["retrievals"],
            tool_calls=obs["tool_calls"],
        )
        if cancel_check:
            cancel_check()
        return StreamResult(content=result, turn=ctx)

    def run_knowledge_ask_stream(self, question: str, user_id: str, thread_id: str = "knowledge",
                                 cb: Callable[[str], None] | None = None,
                                 category: str = "",
                                 scope: str = "all",
                                 mentions: list[dict] | None = None,
                                 attachments: list[dict] | None = None,
                                 cancel_check: Callable[[], None] | None = None,
                                 tools: list[str] | None = None) -> StreamResult:
        """知识库问答：KnowledgeAdvisor 基于 rag_query 检索流式回答（无状态）。

        返回 ``{"content": str, "sources": list[dict]}``：
        sources 为 agent 实际检索到的结构化片段（doc/source/score/text/image_path/page），
        供前端标注来源并点击查看原文。
        category: 检索范围（resume / knowledge / interview），空串检索全部。
        scope: 可见范围（all=公共+本人私有 / public / private）。
        mentions: @ 引用（强制上下文）；由路由层调用 resolve_mentions 后传入 resolved 列表。
        """
        return traced_call(
            self._run_knowledge_ask_stream_impl,
            name="careercrew.knowledge.ask",
            run_type="chain",
            run_metadata={"endpoint": "knowledge.ask"},
            question=question,
            user_id=user_id,
            thread_id=thread_id,
            cb=cb,
            category=category,
            scope=scope,
            mentions=mentions,
            cancel_check=cancel_check,
            tools=tools,
        )

    def _run_knowledge_ask_stream_impl(self, question: str, user_id: str,
                                       thread_id: str = "knowledge",
                                       cb: Callable[[str], None] | None = None,
                                       category: str = "",
                                       scope: str = "all",
                                       mentions: list[dict] | None = None,
                                       attachments: list[dict] | None = None,
                                       cancel_check: Callable[[], None] | None = None,
                                       tools: list[str] | None = None) -> StreamResult:
        from careercrew_api.attachment_context import build_user_message
        from careercrew_api.chat_lifecycle import StreamResult

        attachments = attachments or []
        attach_run_metadata(user_id=user_id, thread_id=thread_id, stage="knowledge")
        ls_run_id = _capture_langsmith_run_id()
        from langchain_core.messages import HumanMessage

        if cancel_check:
            cancel_check()
        # T3.4 §15.3：mention 文档 id 计入强制上下文；resolved mentions 一并写入 user metadata。
        mentions = mentions or []
        forced_doc_ids: list[str] = [
            str(m.get("id") or "") for m in mentions
            if m.get("type") == "knowledge_document" and m.get("id")
        ]
        user_meta: dict = {"category": category, "scope": scope}
        if mentions:
            user_meta["mentions"] = mentions
        if attachments:
            user_meta["attachments"] = attachments
        effective = self.compute_effective_tools("knowledge", tools, user_id=user_id)
        hitl = self._hitl_requires()
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="knowledge", agent_id="knowledge_advisor",
            user_text=question,
            # T1.6：category/scope 存 user metadata，供 regenerate 忠实重跑（同检索范围）。
            # T3.4：mentions 一并记录，供 regenerate 与审计（强制上下文 vs auto 区分）。
            user_metadata=user_meta,
            effective_tools=effective,
        )
        sources: list[dict] = []
        seen: set[str] = set()

        def _sink(r) -> None:
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

        ep = self._get_episodic(thread_id, user_id)
        agent = self.new_knowledge_advisor(
            cb, episodic=ep, rag_sink=_sink, category=category,
            knowledge_access_filters=self._knowledge_scope_filters(user_id, scope),
            forced_doc_ids=forced_doc_ids or None,
            allowed=effective, hitl_requires=hitl,
        )
        try:
            # 先落库用户消息：知识库 agentic 检索 + VLM 读图可能耗时很长，
            # 运行中途被切换/刷新/重启时问题必须仍在
            pending_id = self.record_user_message(
                user_id, thread_id, question, module="knowledge"
            )
        except Exception:
            pending_id = None
        if cancel_check:
            cancel_check()
        state = {
            "thread_id": thread_id, "user_id": user_id, "stage": "knowledge",
            "user_intent": question,
            # 历史由 BaseAgent.history_loader 从 episodic 恢复，这里只放当前问题
            # （+ 本轮附带的附件/引用简历内容）
            "messages": [HumanMessage(content=build_user_message(
                question, attachments + self._mention_blocks(user_id, mentions)
            ))],
            "pending_action": None, "agent_outputs": {}, "target_companies": [],
            # 历史恢复时跳过刚写入的当前问题，避免上下文里重复出现
            "pending_user_entry_id": pending_id,
        }
        if cancel_check:
            cancel_check()
        try:
            agent.run(state)
        except Exception as e:
            self._fail_chat_turn(ctx, e)
            raise
        if cancel_check:
            cancel_check()
        content = (agent.last_result.content or "").strip()
        capped = _cap_sources(
            sources,
            limit=3,
            min_score=0.0,
            keep_paths=_read_image_paths(agent.last_result),
        )
        try:
            self.record_thread_messages(
                user_id, thread_id, user_text="", agent_text=content,
                module="knowledge", sources=capped,
            )
        except Exception:
            pass  # transcript 写入失败不阻塞问答
        # T1.4：检索行来自 _sink 收集的 sources（doc/score 可直接取），正文不落库。
        # T3.4 §15.3：retrieval_source 区分 mention（命中强制上下文 doc）与 auto（自动检索）。
        capped_docs = {_norm_path(s.get("image_path") or "") or s.get("source"): s for s in capped}
        forced_doc_set = set(forced_doc_ids)
        retrievals: list[dict] = []
        for i, s in enumerate(sources):
            key = _norm_path(s.get("image_path") or "") or s.get("source")
            doc = str(s.get("doc") or "")
            retrievals.append({
                "query_index": i,
                "query_text_redacted": question,
                "scope": scope,
                "document_id": doc or None,
                "chunk_id": None,
                "recall_score": float(s.get("score") or 0.0),
                "used_in_final_context": key in capped_docs,
                # 命中 mention 文档 → 'mention'；否则 'auto'（无 mentions 时全 auto）
                "retrieval_source": "mention" if forced_doc_set and doc in forced_doc_set else "auto",
            })
        lr = agent.last_result
        obs = _observability_from_result(lr)
        self._finish_chat_turn(
            ctx, content, metadata={"sources": capped},
            langsmith_run_id=ls_run_id,
            input_tokens=obs["input_tokens"], output_tokens=obs["output_tokens"],
            total_tokens=obs["total_tokens"], retrievals=retrievals,
            tool_calls=obs["tool_calls"],
        )
        if cancel_check:
            cancel_check()
        return StreamResult(content=content, sources=capped, turn=ctx)

    # ── regenerate（§2.3 / §19 / §34 / §38）──
