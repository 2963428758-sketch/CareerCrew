
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:

    pass


pass





class ServicesMixin:
    """记忆操作 + consult 流式 + health。"""

    def memory_list(self, user_id: str, thread_id: str | None = None,
                    type: str = "") -> list[dict]:
        """列出语义事实 + 情景事件（可过滤）。"""
        self._ensure_stores()
        if self.memory_service is not None:
            return self.memory_service.list_records(
                user_id, category=type, limit=100,
            )["items"]
        from careercrew_core.memory.semantic import SemanticFactStore

        facts = [f.model_dump() for f in SemanticFactStore(self.memory_db, user_id).list_facts()]
        memory_thread_id = self._memory_thread_id(thread_id, user_id) if thread_id else None
        rows = self.memory_db.list_episodic(user_id, thread_id=memory_thread_id, type=type or None)
        events = []
        for r in rows:
            content = r.get("content")
            extra: dict = {}
            if isinstance(content, dict):
                # 知识库 agent_response 存的是 {"text": ..., "sources": [...]}
                if "text" in content:
                    extra = {k: v for k, v in content.items() if k != "text"}
                    content = content["text"]
            event: dict = {
                "id": r["id"], "type": r["type"], "ts": r["ts"],
                "parentId": r.get("parent_id"), "content": content,
                "thread_id": r.get("thread_id"),
            }
            event.update(extra)
            events.append(event)
        merged: list[dict] = []
        for f in facts:
            if type and f["type"] != type:
                continue
            merged.append({
                "kind": "fact", "id": f["name"], "type": f["type"], "ts": f["modified_at"],
                "content": f["content"], "name": f["name"],
                "description": f["description"], "source": f["source"],
                "confidence": f["confidence"], "version": f["version"],
            })
        for e in events:
            merged.append({"kind": "event", **e})
        merged.sort(key=lambda x: x.get("ts", ""))
        return merged

    def memory_records(self, user_id: str, *, kind: str = "", category: str = "",
                       query: str = "", limit: int = 20,
                       cursor: str | None = None) -> dict:
        """长期记忆管理页：按类型/分类/关键词过滤的 latest-first 游标列表。"""
        self._ensure_stores()
        if self.memory_service is not None:
            return self.memory_service.list_records(
                user_id, kind=kind, category=category, query=query,
                limit=limit, cursor=cursor,
            )
        rows = self.memory_list(user_id, type=category)
        if kind:
            rows = [row for row in rows if row.get("kind") == kind]
        if query.strip():
            needle = query.casefold().strip()
            rows = [row for row in rows if needle in str(row).casefold()]
        rows.sort(key=lambda row: str(row.get("ts") or ""), reverse=True)
        return {"items": rows[:limit], "next_cursor": None, "total": len(rows)}

    def memory_delete(self, user_id: str, kind: str = "",
                      name: str | None = None, entry_id: str | None = None,
                      thread_id: str | None = None, type: str = "",
                      record_id: str | None = None) -> int:
        """删除语义事实（kind=fact / name）或情景事件（kind=event / entry_id）。"""
        self._ensure_stores()
        if self.memory_service is not None:
            # 删除必须同时清理 Qdrant；因此在此处按需完成重组件初始化。
            self._ensure_heavy()
            self.memory_service._vector_store = self._get_episodic_vector_store()
            return self.memory_service.delete(
                user_id, kind=kind, name=name, entry_id=entry_id,
                thread_id=thread_id, category=type, record_id=record_id,
            )
        from careercrew_core.memory.semantic import SemanticFactStore

        fact_store = SemanticFactStore(self.memory_db, user_id)
        removed = 0
        if kind in ("", "fact") and name:
            removed += fact_store.delete_fact(name)
        elif kind == "fact" and type:
            removed += fact_store.delete_fact(type=type)
        if kind in ("", "event"):
            removed += self.memory_db.delete_episodic(
                user_id, entry_id=entry_id, thread_id=thread_id, type=type or None
            )
        return removed

    def memory_policy_get(self, user_id: str) -> dict:
        self._ensure_heavy()
        g = self.policy_store.global_policy()
        u = self.policy_store.user_policy(user_id)
        eff = (
            self.memory_service.effective_policy(user_id)
            if self.memory_service is not None
            else self.policy_store.effective(user_id, self.settings.memory.enabled)
        )
        return {
            "global": g.model_dump(exclude={"user_id"}),
            "user": u.model_dump(),
            "effective": eff.model_dump(),
        }

    def memory_policy_set(self, user_id: str, enabled: bool | None = None,
                          generate: bool | None = None, use: bool | None = None) -> dict:
        self._ensure_heavy()
        self.policy_store.set_user(user_id, enabled=enabled, generate=generate, use=use)
        return self.memory_policy_get(user_id)

    def memory_settings_get(self) -> dict:
        self._ensure_heavy()
        g = self.policy_store.global_policy()
        return {
            "enabled": bool(self.settings.memory.enabled and g.enabled),
            "feature_enabled": bool(self.settings.memory.enabled),
            "global": g.model_dump(exclude={"user_id"}),
            "router_top_n": self.settings.memory.router.top_n,
            "max_inject_tokens": self.settings.memory.router.max_inject_tokens,
        }

    def memory_settings_set(self, enabled: bool | None = None,
                            generate: bool | None = None, use: bool | None = None) -> dict:
        """全局记忆开关（持久化到 memory_global_policy，settings 文件不动）。"""
        self._ensure_heavy()
        cur = self.policy_store.global_policy()
        self.policy_store.set_global(
            enabled=bool(enabled) if enabled is not None else cur.enabled,
            generate=generate,
            use=use,
        )
        return self.memory_settings_get()

    def memory_consolidate(self, user_id: str, force: bool = False) -> dict:
        """触发后台 consolidation（同步执行，供测试/手动触发）。"""
        self._ensure_heavy()
        if self.memory_service is not None and not self.memory_service.effective_policy(user_id).can_consolidate:
            return {"consolidated": False, "reason": "memory_policy_disabled"}
        from careercrew_core.memory.consolidation import Consolidator

        c = Consolidator(
            self.memory_db,
            min_interval_hours=self.settings.memory.consolidation.min_interval_hours,
            min_sessions=self.settings.memory.consolidation.min_sessions,
        )
        return c.consolidate(user_id, force=force)

    def consult_stream(self, names: list[str], question: str, user_id: str,
                       cb: Callable[[str, str], None] | None = None):
        """并行会诊：fan-out 各 agent -> 读 last_result -> 综合返回。

        cb(agent_name, text) 用于流式回调各 agent 的 chunk。
        返回 ``{opinions: {name: content}, synthesis: str}``。
        """
        self._ensure_heavy()
        from langchain_core.messages import HumanMessage

        from careercrew_core.supervisor.consult import _synthesize

        opinions: dict[str, str] = {}

        def _run_one(name: str) -> str:
            episodic = self._get_episodic("consult", user_id)
            agent = self.new_consult_agent(
                name, episodic=episodic,
            )  # 每 agent 独立实例，无跨会话竞态
            state = {
                "thread_id": "consult", "user_id": user_id, "stage": "review",
                "user_intent": question,
                "messages": [HumanMessage(content=question)],
                "pending_action": None, "agent_outputs": {}, "target_companies": [],
            }
            agent.run(state)
            return (agent.last_result.content or "").strip()

        with ThreadPoolExecutor(max_workers=max(len(names), 1)) as pool:
            futures = {name: pool.submit(_run_one, name) for name in names}
            results = {name: f.result() for name, f in futures.items()}

        for name, content in results.items():
            opinions[name] = content
            if cb:
                cb(name, content)

        synthesis = _synthesize(opinions, question, self.llm)
        return {"opinions": opinions, "synthesis": synthesis}

    # ── health（不触发重初始化）──

    def health_info(self) -> dict:
        """读 settings 不触发 heavy init；ready 反映是否已初始化。"""
        if not self._initialized:
            try:
                from careercrew_core.state.settings import load_settings

                s = load_settings()
                return {
                    "status": "ok", "model": s.llm.model,
                    "embedding": s.embedding.provider,
                    "vector_store": s.vector_store.backend,
                    "ready": False,
                }
            except Exception as e:
                return {"status": "ok", "ready": False, "error": str(e)}
        return {
            "status": "ok", "model": self.settings.llm.model,
            "embedding": self.settings.embedding.provider,
            "vector_store": self.settings.vector_store.backend,
            "ready": True,
        }
