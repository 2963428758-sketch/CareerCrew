
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from careercrew_core.tracing.langsmith import (
    attach_run_metadata,
    traced_call,
)

if TYPE_CHECKING:

    pass


pass





class ToolsAgentsMixin:
    """agent 工厂 + 工具集装配 + 历史装载/HITL/effective tools。"""

    def _thread_history_messages(self, user_id: str, thread_id: str,
                                 max_rounds: int = 10,
                                 exclude_entry_id: str | None = None) -> list:
        """从 ConversationStore 恢复历史；旧 episodic transcript 仅作只读回退。

        ``exclude_entry_id`` 是当前轮 conversation user message id；本轮问题由
        调用方单独传给 Agent，因此这里跳过它以避免上下文重复。
        """
        from langchain_core.messages import AIMessage, HumanMessage

        rows: list[dict] = []
        conversation_found = False
        if self.conversation_store is not None:
            try:
                conversation_found = self.conversation_store.get_conversation(
                    thread_id, user_id
                ) is not None
                if conversation_found:
                    rows = self.conversation_store.list_messages(thread_id, user_id)
            except Exception:
                conversation_found = False

        msgs: list = []
        if conversation_found:
            for row in rows:
                if exclude_entry_id and row.get("id") == exclude_entry_id:
                    continue
                content = row.get("content")
                if not content:
                    continue
                if row.get("role") == "user":
                    msgs.append(HumanMessage(content=content))
                elif row.get("role") == "assistant":
                    msgs.append(AIMessage(content=content))
        elif self.memory_db is not None:
            # 迁移期兼容：只读取历史版本已经写入的 transcript，不再产生新记录。
            legacy_rows = self.memory_db.list_episodic(
                user_id, thread_id=self._memory_thread_id(thread_id, user_id), type=None
            )
            for row in legacy_rows:
                if exclude_entry_id and row.get("id") == exclude_entry_id:
                    continue
                if row.get("type") not in ("user_message", "agent_response"):
                    continue
                content = row.get("content")
                if isinstance(content, dict) and "text" in content:
                    content = content["text"]
                if not content:
                    continue
                message_cls = HumanMessage if row["type"] == "user_message" else AIMessage
                msgs.append(message_cls(content=content))
        # 保留最近 max_rounds 轮（user+agent 两条一轮）
        return msgs[-(max_rounds * 2):]

    # ── agent 工厂（每次 new 一套，避免 last_result 并发串写）──

    def _get_episodic_vector_store(self):
        """情景记忆专用向量 store（Qdrant careercrew_episodic_v2；测试/缺 embedding 时降级）。"""
        if self._episodic_vector_store is not None:
            return self._episodic_vector_store
        if self.settings is None or self.embedding is None:
            return None
        col = self.settings.vector_store.collections.get(
            "episodic_memory", "careercrew_episodic_v2"
        )
        if self.settings.vector_store.backend == "fake":
            from careercrew_ai.vector_store import create_vector_store

            self._episodic_vector_store = create_vector_store(self.settings)
        else:
            from careercrew_ai.vector_store.qdrant_store import QdrantStore

            self._episodic_vector_store = QdrantStore(
                self.settings, collection_name=col
            )
        return self._episodic_vector_store

    def _make_vector_index(self, episodic, user_id: str):
        """构造 per-user 情景记忆向量索引（向量化关闭或 embedding 缺失时返回 None）。"""
        if not self.settings.memory.episodic.vectorize or self.embedding is None:
            return None
        vs = self._get_episodic_vector_store()
        if vs is None:
            return None
        from careercrew_core.memory.vector_index import VectorIndex

        return VectorIndex(self.embedding, vs, episodic, user_id=user_id)

    def _compaction_kwargs(self) -> dict:
        """从配置构造 ContextCompactionMiddleware 参数（compaction 关闭时返回 None 标记）。"""
        cfg = self.settings.memory.compaction
        if not cfg.enabled:
            return {}
        return {
            "token_threshold_ratio": cfg.token_threshold_ratio,
            "retention_tokens": cfg.retention_tokens,
        }

    def _history_loader(self, user_id: str, thread_id: str,
                        exclude_entry_id: str | None = None):
        """从 canonical conversation 恢复历史（供 BaseAgent.history_loader）。"""
        try:
            return self._thread_history_messages(
                user_id, thread_id, exclude_entry_id=exclude_entry_id
            )
        except Exception:
            return []

    def _hitl_requires(self) -> set[str]:
        """本轮需 HITL 确认的工具名集合（settings.tools.hitl.requires_confirmation）。"""
        tools = getattr(self.settings, "tools", None)
        hitl = getattr(tools, "hitl", None) if tools is not None else None
        return set(getattr(hitl, "requires_confirmation", None) or [])

    def _server_allowlist(self, module: str) -> list[str]:
        """服务端 module allowlist（单一事实来源，与 capabilities 一致）。

        = settings.tools.registry（internal+mcp 全量）∩ module 声明（MODULE_TOOLS）。
        module 未在 MODULE_TOOLS 声明时视为不约束（全量 registry）。
        """
        from careercrew_core.tools.capabilities import MODULE_TOOLS

        reg = getattr(getattr(self.settings, "tools", None), "registry", None)
        if reg is None:
            return []
        registry: list[str] = []
        for n in list(getattr(reg, "internal", None) or []) + list(getattr(reg, "mcp", None) or []):
            if n not in registry:
                registry.append(n)
        module_allow = MODULE_TOOLS.get(module)
        if module_allow is None:
            return registry
        allow = set(module_allow)
        return [n for n in registry if n in allow]

    def _apply_memory_policy_to_tools(self, names: list[str], user_id: str | None) -> list[str]:
        """按统一生效策略裁剪 Memory 工具；缺少用户上下文时保持兼容行为。"""
        if not user_id or self.policy_store is None or self.settings is None:
            return names
        memory_cfg = getattr(self.settings, "memory", None)
        if memory_cfg is None or not hasattr(memory_cfg, "enabled"):
            return names
        policy = self.policy_store.effective(user_id, bool(memory_cfg.enabled))
        blocked: set[str] = set()
        if not policy.enabled:
            blocked.update({"memory_search", "memory_write", "profile_update"})
        else:
            if not policy.use:
                blocked.add("memory_search")
            if not policy.generate:
                blocked.update({"memory_write", "profile_update"})
        return [name for name in names if name not in blocked]

    def compute_effective_tools(self, module: str, client_requested: list[str] | None,
                                user_id: str | None = None) -> list[str]:
        """本轮最终工具集合，并在 Agent 构造前执行用户级 Memory Policy。"""
        from careercrew_core.tools.effective import compute_effective_tools

        names = compute_effective_tools(
            client_requested, self._server_allowlist(module),
        )
        return self._apply_memory_policy_to_tools(names, user_id)

    def _make_tools(self, kind: str, episodic=None, rag_sink=None, rag_category=None,
                    knowledge_access_filters: dict | None = None,
                    forced_doc_ids: list[str] | None = None,
                    allowed: list[str] | None = None):
        """构造 agent 工具集；必须显式携带认证用户的 episodic 上下文。"""
        from careercrew_core.memory.semantic import SemanticFactStore
        from careercrew_core.tools.browser.boss_apply import make_send_greeting_tool
        from careercrew_core.tools.internal.memory_search import make_memory_search_tool
        from careercrew_core.tools.internal.memory_write import make_memory_write_tool
        from careercrew_core.tools.internal.profile_update import make_profile_update_tool
        from careercrew_core.tools.internal.rag_query import make_rag_query_tool
        from careercrew_core.tools.internal.read_image import make_read_image_tool
        from careercrew_core.tools.internal.salary_query import make_salary_query_tool
        from careercrew_core.tools.internal.search_jobs import make_search_jobs_tool
        from careercrew_core.tools.mcp.mock_apply import send_greeting, submit_application
        from careercrew_core.tools.registry import ToolRegistry, ToolSpec

        if episodic is None:
            raise ValueError("episodic context is required for tenant-scoped agent tools")
        ep = episodic
        hs = self.multimodal_search
        user_id = ep.user_id
        vi = self._make_vector_index(ep, user_id)
        user_facts = SemanticFactStore(self.memory_db, user_id)
        tools = ToolRegistry()
        mem_search = make_memory_search_tool(
            vector_index=vi,
            fact_store=user_facts,
            router=self.memory_router,
            memory_service=self.memory_service,
            user_id=user_id,
        )
        from careercrew_core.rag.categories import categories_for_agent

        # 每个 agent 的 rag_query 只检索对应分类（knowledge 分支由 rag_category 用户选择控制）
        cats = categories_for_agent(kind)
        # 强制上下文（T3.4 §15.3）：mentions 命中的 knowledge 文档叠加 doc 白名单，
        # 与 auto RAG 共用 rag_query 接缝（knowledge/planner/matcher 等均适用）。
        def _rag_filters(base: dict) -> dict:
            if forced_doc_ids:
                return {**base, "doc": list(forced_doc_ids)}
            return base

        # M5 CRAG：rag.retrieval.crag 开启时为 rag_query 注入评估器
        # （incorrect -> LLM 重写查询重检一轮）；默认 None 行为不变。
        crag_factory = None
        try:
            if self.settings.rag.retrieval.crag:
                from careercrew_ai.llm import create_llm
                from careercrew_core.rag.retrieval.retrieval_assessor import RetrievalAssessor

                crag_llm = create_llm(self.settings, max_tokens=256)

                def _crag_factory(search_fn):
                    return RetrievalAssessor(crag_llm, search_fn)

                crag_factory = _crag_factory
        except Exception:
            pass

        if kind == "matcher":
            boss_cfg = getattr(self.settings.tools, "search", None)
            tools.register(ToolSpec(tool=make_search_jobs_tool(
                self.jobs_store,
                boss_cdp_url=getattr(boss_cfg, "boss_cdp_url", "") or "",
                boss_city=getattr(boss_cfg, "boss_city", "") or "",
            )))
            tools.register(ToolSpec(tool=make_rag_query_tool(
                hs, categories=cats, filters=_rag_filters({"user_id": user_id}), assessor=crag_factory,
                )))
            tools.register(ToolSpec(tool=make_memory_write_tool(
                ep, vi, memory_service=self.memory_service, user_id=user_id,
            )))
            tools.register(ToolSpec(tool=mem_search))
            tools.register(ToolSpec(tool=make_profile_update_tool(
                SemanticFactStore(self.memory_db, user_id), user_id=user_id,
                source="job_matcher", memory_service=self.memory_service)))
            # T3.5 HITL MVP 的实际生产绑定：投递动作必须先经过
            # HitlMiddleware；当前无 approve/reject 恢复协议时绝不执行工具函数。
            tools.register(ToolSpec(tool=submit_application, requires_confirmation=True))
            # N2：配置 Boss CDP 后 send_greeting 变真（详情页发起沟通+发送+验证+
            # apply_attempt 留痕），未配置时注册 mock 版保持原行为。
            boss_cdp = getattr(boss_cfg, "boss_cdp_url", "") or ""
            greeting_tool = (
                make_send_greeting_tool(
                    cdp_url=boss_cdp, episodic_factory=lambda: ep,
                    memory_service=self.memory_service, user_id=user_id,
                )
                if boss_cdp else send_greeting
            )
            tools.register(ToolSpec(tool=greeting_tool, requires_confirmation=True))
        elif kind == "resume":
            tools.register(ToolSpec(tool=make_rag_query_tool(
                hs, categories=cats, filters=_rag_filters({"user_id": user_id}), assessor=crag_factory,
                )))
            tools.register(ToolSpec(tool=make_profile_update_tool(
                SemanticFactStore(self.memory_db, user_id), user_id=user_id,
                source="resume_advisor", memory_service=self.memory_service)))
        elif kind == "interviewer":
            tools.register(ToolSpec(tool=make_rag_query_tool(
                hs, categories=cats, filters=_rag_filters({"user_id": user_id}), assessor=crag_factory,
                )))
            tools.register(ToolSpec(tool=make_memory_write_tool(
                ep, vi, memory_service=self.memory_service, user_id=user_id,
            )))
            tools.register(ToolSpec(tool=mem_search))
        elif kind == "salary":
            tools.register(ToolSpec(tool=make_rag_query_tool(
                hs, categories=cats, filters=_rag_filters({"user_id": user_id}), assessor=crag_factory,
                )))
            tools.register(ToolSpec(tool=make_profile_update_tool(
                SemanticFactStore(self.memory_db, user_id), user_id=user_id,
                source=kind, memory_service=self.memory_service)))
            tools.register(ToolSpec(tool=mem_search))
            tools.register(ToolSpec(tool=make_salary_query_tool()))
        elif kind == "planner":
            # 职业规划师：求职对话页的主理 agent，职责聚焦求职规划
            tools.register(ToolSpec(tool=make_rag_query_tool(
                hs, categories=cats, filters=_rag_filters({"user_id": user_id}), assessor=crag_factory,
                )))
            tools.register(ToolSpec(tool=make_profile_update_tool(
                SemanticFactStore(self.memory_db, user_id), user_id=user_id,
                source="career_planner", memory_service=self.memory_service)))
            tools.register(ToolSpec(tool=mem_search))
            tools.register(ToolSpec(tool=make_salary_query_tool()))
        elif kind == "knowledge":
            # T3.4 §15.3 强制上下文：mentioned 的 knowledge 文档通过 doc 过滤限定为本轮检索范围，
            # 与 auto RAG（category/scope 过滤）共用 rag_query 接缝，仅额外叠加 doc 白名单。
            kf = {**dict(knowledge_access_filters or {"__access_user": user_id})}
            if forced_doc_ids:
                kf["doc"] = list(forced_doc_ids)
            tools.register(ToolSpec(tool=make_rag_query_tool(
                hs, sink=rag_sink, categories=rag_category or None,
                filters=kf, assessor=crag_factory,
            )))
            # 个人背景问题（学校/专业/教育等）常藏在简历页图里，允许顾问按需读图
            tools.register(ToolSpec(tool=make_read_image_tool(
                self.settings,
                path_authorizer=lambda path: self.knowledge_asset_owned(user_id, path),
            )))
            # "我有哪些项目/技能/目标公司" 等个人记忆问题：允许查语义事实 + 情景事件
            tools.register(ToolSpec(tool=mem_search))
        # T3.5 §16.3：allowed 非 None 时裁剪到最终集合（client ∩ server allowlist 已在上游算好）。
        # None = 默认全放行（保持既有行为）。
        policy_allowed = set(self._apply_memory_policy_to_tools(
            [spec.name for spec in tools.list_specs()], user_id,
        ))
        if allowed is not None or len(policy_allowed) != len(tools.list_specs()):
            allowed_set = set(allowed) if allowed is not None else policy_allowed
            allowed_set &= policy_allowed
            filtered = ToolRegistry()
            for spec in tools.list_specs():
                if spec.name in allowed_set:
                    filtered.register(spec)
            return filtered
        return tools

    def _resolve_llm(self, episodic=None):
        uid = getattr(episodic, "user_id", None) if episodic else None
        return self.get_llm_for_user(uid)

    def new_job_matcher(self, cb: Callable[[str], None] | None = None, episodic=None,
                        allowed: list[str] | None = None, hitl_requires: set[str] | None = None,
                        forced_doc_ids: list[str] | None = None):
        self._ensure_heavy()
        from careercrew_core.agents.job_matcher import JobMatcher

        return JobMatcher(
            llm=self._resolve_llm(episodic), tools=self._make_tools("matcher", episodic=episodic, allowed=allowed,
                                                  forced_doc_ids=forced_doc_ids),
            max_iterations=8, stream_callback=cb, memory_injector=self.memory_injector,
            history_loader=self._history_loader,
            compaction=self._compaction_kwargs() or None,
            hitl_requires=hitl_requires,
        )

    def new_resume_advisor(self, cb: Callable[[str], None] | None = None, episodic=None,
                           allowed: list[str] | None = None, hitl_requires: set[str] | None = None,
                           forced_doc_ids: list[str] | None = None):
        self._ensure_heavy()
        from careercrew_core.agents.resume_advisor import ResumeAdvisor

        return ResumeAdvisor(
            llm=self._resolve_llm(episodic), tools=self._make_tools("resume", episodic=episodic, allowed=allowed,
                                                  forced_doc_ids=forced_doc_ids),
            max_iterations=15, stream_callback=cb, memory_injector=self.memory_injector,
            history_loader=self._history_loader,
            compaction=self._compaction_kwargs() or None,
            hitl_requires=hitl_requires,
        )

    def new_interviewer(self, cb: Callable[[str], None] | None = None, episodic=None,
                        prompt_path=None, allowed: list[str] | None = None,
                        hitl_requires: set[str] | None = None,
                        forced_doc_ids: list[str] | None = None):
        self._ensure_heavy()
        from careercrew_core.agents.interviewer import Interviewer

        return Interviewer(
            llm=self._resolve_llm(episodic), tools=self._make_tools("interviewer", episodic=episodic, allowed=allowed,
                                                  forced_doc_ids=forced_doc_ids),
            max_iterations=15, stream_callback=cb, prompt_path=prompt_path,
            memory_injector=self.memory_injector,
            history_loader=self._history_loader,
            compaction=self._compaction_kwargs() or None,
            hitl_requires=hitl_requires,
        )

    def new_knowledge_advisor(self, cb: Callable[[str], None] | None = None, episodic=None,
                              rag_sink=None, category: str = "",
                              knowledge_access_filters: dict | None = None,
                              forced_doc_ids: list[str] | None = None,
                              allowed: list[str] | None = None,
                              hitl_requires: set[str] | None = None):
        self._ensure_heavy()
        from careercrew_core.agents.knowledge_advisor import KnowledgeAdvisor
        from careercrew_core.rag.categories import category_label

        prompt_suffix = ""
        if category:
            prompt_suffix = (
                f"\n\n（本次检索范围：分类「{category_label(category)}」，"
                "rag_query 只会检索该分类，回答以该分类内容为准。）"
            )
        return KnowledgeAdvisor(
            llm=self._resolve_llm(episodic),
            tools=self._make_tools(
                "knowledge", episodic=episodic, rag_sink=rag_sink, rag_category=category,
                knowledge_access_filters=knowledge_access_filters,
                forced_doc_ids=forced_doc_ids, allowed=allowed,
            ),
            max_iterations=15, stream_callback=cb, memory_injector=self.memory_injector,
            history_loader=self._history_loader,
            compaction=self._compaction_kwargs() or None,
            prompt_suffix=prompt_suffix,
            hitl_requires=hitl_requires,
        )

    def new_career_planner(self, cb: Callable[[str], None] | None = None, episodic=None,
                           allowed: list[str] | None = None, hitl_requires: set[str] | None = None,
                           forced_doc_ids: list[str] | None = None):
        """职业规划师（求职对话主理人）：聚焦求职规划，建画像、定目标公司池、做阶段规划与复盘。"""
        self._ensure_heavy()
        from careercrew_core.agents.career_planner import CareerPlanner

        return CareerPlanner(
            llm=self._resolve_llm(episodic), tools=self._make_tools("planner", episodic=episodic, allowed=allowed,
                                                  forced_doc_ids=forced_doc_ids),
            max_iterations=15, stream_callback=cb, memory_injector=self.memory_injector,
            history_loader=self._history_loader,
            compaction=self._compaction_kwargs() or None,
            hitl_requires=hitl_requires,
        )

    def new_consult_agent(self, name: str, cb: Callable[[str], None] | None = None, episodic=None,
                          allowed: list[str] | None = None,
                          hitl_requires: set[str] | None = None):
        """按名字建会诊 agent（T3.5：透传 effective allowed + hitl_requires）。"""
        self._ensure_heavy()
        if name == "salary_negotiator":
            from careercrew_core.agents.salary_negotiator import SalaryNegotiator

            return SalaryNegotiator(
                llm=self._resolve_llm(episodic), tools=self._make_tools("salary", episodic=episodic, allowed=allowed),
                max_iterations=15, stream_callback=cb, memory_injector=self.memory_injector,
                history_loader=self._history_loader,
                compaction=self._compaction_kwargs() or None,
                hitl_requires=hitl_requires,
            )
        if name == "career_planner":
            return self.new_career_planner(cb, episodic=episodic, allowed=allowed,
                                           hitl_requires=hitl_requires)
        if name == "job_matcher":
            return self.new_job_matcher(cb, episodic=episodic, allowed=allowed,
                                        hitl_requires=hitl_requires)
        if name == "resume_advisor":
            return self.new_resume_advisor(cb, episodic=episodic, allowed=allowed,
                                           hitl_requires=hitl_requires)
        if name == "interviewer":
            return self.new_interviewer(cb, episodic=episodic, allowed=allowed,
                                        hitl_requires=hitl_requires)
        raise ValueError(f"未知会诊 agent: {name}")

    # ── 直通方法 ──

    def score_answer(self, question: str, answer: str, max_score: int = 10) -> dict:
        return traced_call(
            self._score_answer_impl,
            name="careercrew.interview.score",
            run_type="chain",
            run_metadata={"endpoint": "interview.score"},
            question=question,
            answer=answer,
            max_score=max_score,
        )

    def _score_answer_impl(self, question: str, answer: str, max_score: int = 10) -> dict:
        attach_run_metadata(stage="interview")
        self._ensure_heavy()
        from careercrew_core.agents.interviewer import score_answer

        return score_answer(question, answer, self.llm, max_score=max_score)

    def record_interview_qa(self, user_id: str, thread_id: str, entries: list[dict]) -> int:
        self._ensure_heavy()
        from careercrew_core.agents.interviewer import record_interview_qa

        episodic = self._get_episodic(thread_id, user_id)
        vi = self._make_vector_index(episodic, user_id=user_id)
        return record_interview_qa(
            episodic, entries, vector_index=vi,
            memory_service=self.memory_service, user_id=user_id,
        )

    # ── 记忆管理 API（数据看板 / 治理） ──
