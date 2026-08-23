
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from careercrew_api.runtime.common import (
    ResourceNotFoundError,
)

if TYPE_CHECKING:

    pass


pass




class TurnLifecycleMixin:
    """会话轮次生命周期 + 标题生成 + 线程 CRUD（ThreadService 职责）。"""

    def _conversation_model(self) -> str:
        """当前 run 的 model（settings.llm.model；未初始化时退化空串）。"""
        if self.settings is None:
            return ""
        return getattr(self.settings.llm, "model", "") or ""

    def _begin_chat_turn(self, thread_id: str, user_id: str, module: str,
                         agent_id: str, user_text: str, title: str | None = None,
                         user_metadata: dict | None = None,
                         effective_tools: list[str] | None = None):
        """开启一轮对话（conversation 表四件套），失败不阻断主流程（返回 None）。

        prompt_version / agent_version 由 versioning 按 agent_id 计算（T1.5）：
        - 有单一 agent prompt 的入口写 sha256:<64hex>
        - 编排类入口（consult_orchestrator 无单一 prompt）→ agent_id 未注册 → unversioned，
          Phase 2/3 补编排级版本时再换。
        user_metadata（T1.6）：写入 user 消息 metadata，供 regenerate 忠实重跑。
        """
        from careercrew_api.chat_lifecycle import begin_turn
        from careercrew_core.versioning import agent_version, prompt_version_for_agent

        self._ensure_heavy()
        try:
            ctx = begin_turn(
                self.conversation_store,
                thread_id=thread_id, user_id=user_id, module=module,
                agent_id=agent_id, user_text=user_text,
                model=self._conversation_model(), title=title,
                prompt_version=prompt_version_for_agent(agent_id),
                agent_version=agent_version(),
                user_metadata=user_metadata,
                effective_tools=effective_tools,
            )
            # Conversation 仍是全文唯一事实源。这里只把通过确定性高精度规则的
            # 稳定职业自述交给 MemoryService；普通聊天绝不会被复制为长期记忆。
            service = getattr(self, "memory_service", None)
            if service is not None:
                try:
                    service.capture_text_candidates(user_id, user_text, source="conversation")
                except PermissionError:
                    pass  # 记忆关闭/禁止生成是正常策略结果，不影响对话。
                except Exception:
                    import logging
                    logging.getLogger(__name__).warning("memory candidate capture failed", exc_info=True)
            return ctx
        except Exception:
            import logging
            logging.getLogger(__name__).exception("begin_chat_turn failed")
            return None

    def _finish_chat_turn(self, ctx, content: str, status: str = "completed",
                          metadata: dict | None = None,
                          input_tokens: int | None = None,
                          output_tokens: int | None = None,
                          total_tokens: int | None = None,
                          langsmith_run_id: str | None = None,
                          retrievals: list[dict] | None = None,
                          tool_calls: list[dict] | None = None) -> None:
        """收尾一轮对话（写 assistant content + 状态 + 可选 metadata 富结构 + run latency
        + T1.4 观测字段）；ctx 为 None 时跳过。"""
        from careercrew_api.chat_lifecycle import finish_turn

        if ctx is None:
            return
        try:
            finish_turn(
                self.conversation_store, ctx, content, status=status, metadata=metadata,
                input_tokens=input_tokens, output_tokens=output_tokens,
                total_tokens=total_tokens, langsmith_run_id=langsmith_run_id,
                retrievals=retrievals, tool_calls=tool_calls,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("finish_chat_turn failed")
        self._maybe_generate_first_title(ctx, content)

    def _generate_title(self, user_text: str, assistant_text: str) -> str:
        """用现有对话模型为首轮问答生成短标题；返回空串表示不可用。"""
        from careercrew_core.memory.redaction import redact_secrets

        user = redact_secrets(user_text or "")[:1200]
        assistant = redact_secrets(assistant_text or "")[:2400]
        prompt = (
            "请根据下面的用户问题和助手回答，生成一个简洁的中文会话标题。\n"
            "要求：只输出标题本身，不要引号、编号、Markdown 或解释；不超过18个汉字，概括主题而不是复述整句。\n\n"
            f"用户问题：\n{user}\n\n助手回答：\n{assistant}"
        )
        response = self.llm.invoke(prompt)
        raw = getattr(response, "content", "")
        if isinstance(raw, list):
            parts: list[str] = []
            for item in raw:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            raw = "".join(parts)
        title = str(raw or "").strip().splitlines()[0] if str(raw or "").strip() else ""
        title = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"^(?:标题|title)\s*[:：]\s*", "", title, flags=re.IGNORECASE)
        title = title.strip(" `\"'“”‘’《》")
        title = re.sub(r"[。！？.!?]+$", "", title).strip()
        return title[:30]

    def _maybe_generate_first_title(self, ctx, assistant_text: str) -> None:
        """首轮回答完成后更新同一 conversation/memory 线程标题，失败不影响主流程。"""
        if ctx is None or not getattr(ctx, "user_message_id", ""):
            return
        if self.conversation_store is None or self.thread_store is None or self.llm is None:
            return
        try:
            turn = self.conversation_store.get_turn(ctx.user_id, ctx.turn_id)
            if not turn or int(turn.get("sequence_no") or 0) != 1:
                return
            user_message = self.conversation_store.get_message(ctx.user_id, ctx.user_message_id)
            user_text = str((user_message or {}).get("content") or "").strip()
            if not user_text or not assistant_text:
                return
            title = self._generate_title(user_text, assistant_text)
            if not title:
                return

            self.conversation_store.rename_title(ctx.thread_id, ctx.user_id, title)
            memory_thread_id = self._memory_thread_id(ctx.thread_id, ctx.user_id)
            existing = self.thread_store.get(ctx.user_id, memory_thread_id)
            self.thread_store.upsert(
                ctx.user_id,
                memory_thread_id,
                title=title,
                module=ctx.module,
                pinned=bool((existing or {}).get("pinned")),
                retrieval_scope=(existing or {}).get("retrieval_scope"),
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("first-turn title generation failed")

    def _fail_chat_turn(self, ctx, exc: BaseException) -> None:
        from careercrew_api.chat_lifecycle import fail_turn

        if ctx is None:
            return
        try:
            fail_turn(self.conversation_store, ctx, exc)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("fail_chat_turn failed")

    def _cancel_chat_turn(self, ctx) -> None:
        from careercrew_api.chat_lifecycle import cancel_turn

        if ctx is None:
            return
        try:
            cancel_turn(self.conversation_store, ctx)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("cancel_chat_turn failed")

    def _ensure_thread(self, thread_id: str, user_id: str, module: str = "chat",
                       title: str = "") -> None:
        """确保线程元数据存在（首次使用时登记，供侧边栏列表）。"""
        self._ensure_heavy()
        ts = self.thread_store
        memory_thread_id = self._memory_thread_id(thread_id, user_id)
        existing = ts.get(user_id, memory_thread_id)
        if existing is None:
            ts.upsert(user_id, memory_thread_id, title=title[:50], module=module)
        elif title and not existing.get("title"):
            ts.upsert(user_id, memory_thread_id, title=title[:50], module=module,
                      pinned=bool(existing.get("pinned")))

    def _memory_thread_id(self, thread_id: str, user_id: str) -> str:
        """将 conversation UUID 归一到对应的 legacy memory thread id。

        conversation 表是 UUID 主表，memory threads 表仍兼容旧的 ``t-*`` 等 id。
        两张表之间如果已有 legacy 映射，所有 memory 读写都必须使用同一个 key，
        否则同一会话在第二轮会被拆成两条侧边栏历史。
        """
        if not thread_id or self.conversation_store is None:
            return thread_id
        try:
            conversation = self.conversation_store.get_conversation(thread_id, user_id)
        except Exception:
            return thread_id
        return str(conversation.get("legacy_thread_id") or thread_id) if conversation else thread_id

    def record_thread_messages(
        self,
        user_id: str,
        thread_id: str,
        user_text: str,
        agent_text: str,
        module: str = "chat",
        sources: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> int:
        """兼容旧路由的空操作；conversation lifecycle 已持久化完整消息。

        普通 transcript 不是长期记忆。保留方法签名直到各调用点完成迁移，避免
        旧路由因为缺少方法而失败。
        """
        return 0

    def record_user_message(self, user_id: str, thread_id: str, user_text: str,
                            module: str = "chat") -> str | None:
        """返回 canonical 当前用户消息 ID，不再写入 episodic memory。

        ``_begin_chat_turn`` 已在 Agent 执行前持久化用户消息，因此即使长期记忆
        关闭，失败和刷新恢复仍然成立。
        """
        if not user_text:
            return None
        if self.conversation_store is None:
            return None
        try:
            rows = self.conversation_store.list_messages(thread_id, user_id)
        except Exception:
            return None
        for row in reversed(rows):
            if row.get("role") == "user" and row.get("content") == user_text:
                return str(row["id"])
        return None

    def get_threads(self, user_id: str, module: str | None = None) -> list[dict]:
        """列出用户的所有对话线程，并按 conversation 映射去重 legacy/UUID 别名。"""
        self._ensure_stores()
        rows = self.thread_store.list(user_id, module=module)
        merged: dict[str, dict] = {}
        source_ids: dict[str, str] = {}
        for row in rows:
            memory_thread_id = self._memory_thread_id(
                str(row.get("thread_id") or ""), user_id
            )
            normalized = {**row, "thread_id": memory_thread_id}
            current = merged.get(memory_thread_id)
            source_id = str(row.get("thread_id") or "")
            # 已有稳定 legacy 行优先；UUID 别名只用于补齐没有 legacy 行的旧数据。
            if current is None or (
                source_id == memory_thread_id
                and source_ids.get(memory_thread_id) != memory_thread_id
            ):
                merged[memory_thread_id] = normalized
                source_ids[memory_thread_id] = source_id
        return sorted(
            merged.values(),
            key=lambda row: (
                bool(row.get("pinned")),
                str(row.get("updated_at") or row.get("created_at") or ""),
            ),
            reverse=True,
        )

    def register_thread(self, thread_id: str, user_id: str,
                        module: str = "chat", title: str = "",
                        retrieval_scope: dict | None = None) -> dict:
        """登记线程（前端新会话时调用）。"""
        self._ensure_stores()
        return self.thread_store.upsert(
            user_id, thread_id, title=title, module=module,
            retrieval_scope=retrieval_scope,
        )

    def touch_thread(self, thread_id: str, user_id: str, title: str | None = None,
                     pinned: bool | None = None, module: str | None = None,
                     retrieval_scope: dict | None = None) -> dict:
        """更新线程标题/置顶/检索范围（PATCH）。"""
        self._ensure_stores()
        row = self.thread_store.get(user_id, thread_id)
        if row is None:
            raise ResourceNotFoundError(f"thread not found: {thread_id}")
        return self.thread_store.upsert(
            user_id, thread_id,
            title=title if title is not None else row.get("title", ""),
            module=module or row.get("module") or "chat",
            pinned=pinned if pinned is not None else bool(row.get("pinned")),
            retrieval_scope=retrieval_scope if retrieval_scope is not None
            else row.get("retrieval_scope"),
        )

    def delete_thread(self, thread_id: str, user_id: str) -> dict:
        """删除线程：情景事件 + 线程元数据。"""
        self._ensure_stores()
        if self.thread_store.get(user_id, thread_id) is None:
            raise ResourceNotFoundError(f"thread not found: {thread_id}")
        n = self.thread_store.delete_all_for_thread(user_id, thread_id)
        return {"deleted": n > 0, "thread_id": thread_id, "removed": n}
