"""API 测试 fixtures：FakeRuntime 注入 + web marker。

FakeRuntime duck-types CareerCrewRuntime，不触发任何重组件初始化。
测试用 ``app.dependency_overrides[get_runtime_dep] = lambda: FakeRuntime()`` 无缝换 fake。
"""
from __future__ import annotations

from collections.abc import Callable

import pytest


class FakeRuntime:
    """测试用假运行时（duck-typed，不初始化重组件）。"""

    def __init__(self) -> None:
        self._initialized = True
        self.match_output = "匹配到字节跳动 0.95 / 腾讯 0.85"
        self.resume_output = "定制简历完成，匹配度 0.97"
        self.planner_output = "规划完成：冲刺字节/阿里，匹配美团/腾讯，阶段 0-3 月补 RAG 深度"
        self.interview_output = "1. 请讲讲你对 RAG 的理解\n2. 如何优化召回质量？"
        self.score_result = {"score": 8.5, "feedback": "回答结构清晰，可补充具体案例"}
        self.consult_opinions = {
            "salary_negotiator": "建议薪资 30-35K",
            "career_planner": "建议先积累 Agent 项目经验",
        }
        self.consult_synthesis = "综合建议：先积累经验，谈薪 30-35K"
        self._orchestrator_calls = 0
        self.orchestrator_override = None
        self.knowledge_output = "RAG 检索流程：先解析文档，再切分向量化，最后混合检索重排。（来源：note.md）"
        # 模拟 agent 多轮迭代时中间轮的"开头话"（只进流式 chunk，不进最终内容）
        self.stream_preamble = ""
        self.knowledge_sources = [
            {
                "doc": "note",
                "source": "data/uploads/note.md",
                "score": 0.91,
                "text": "RAG 检索流程：先解析文档，再切分向量化，最后混合检索重排。",
                "image_path": "",
                "page": None,
            }
        ]
        self.last_call: dict = {}
        self.ingest_calls: list = []
        self.knowledge_output_by_user: dict[str, str] = {}
        self.knowledge_ask_scopes: list[str] = []
        self.knowledge_sources_by_user: dict[str, list[dict]] = {}
        self.knowledge_asset_owners: dict[str, str] = {}
        self.match_chunks: list[str] = []
        self.resume_chunks: list[str] = []
        self.upload_content = "解析出的简历文本内容"
        self.upload_error: Exception | None = None
        self.ingest_error: Exception | None = None
        self.knowledge_docs: list[dict] = [
            {"doc": "note", "source": "data/uploads/note.md", "points": 3}
        ]
        self.knowledge_docs_by_user: dict[str, list[dict]] = {
            "u_001": self.knowledge_docs,
        }
        from careercrew_core.memory.db import FakeMemoryDb
        from careercrew_core.memory.injection import MemoryInjector
        from careercrew_core.memory.policy import MemoryPolicyStore
        from careercrew_core.memory.router import MemoryRouter
        from careercrew_core.memory.semantic import SemanticFactStore
        from careercrew_core.memory.threads import ThreadStore
        from careercrew_core.conversation.db import FakeConversationDb
        from careercrew_core.conversation.store import ConversationStore

        self.memory_db = FakeMemoryDb()
        self.conversation_store = ConversationStore(FakeConversationDb())
        self.fact_store = SemanticFactStore(self.memory_db, user_id="u_001")
        self.policy_store = MemoryPolicyStore(self.memory_db)
        self.thread_store = ThreadStore(self.memory_db)
        self.memory_router = MemoryRouter()
        self.memory_injector = MemoryInjector(
            db=self.memory_db, policy_store=self.policy_store,
            router=self.memory_router, feature_enabled=False,
        )
        self.settings = type("S", (), {
            "memory": type("M", (), {
                "enabled": False,
                "router": type("R", (), {"top_n": 5, "max_inject_tokens": 2000}),
                "consolidation": type("C", (), {"min_interval_hours": 24, "min_sessions": 5}),
                "episodic": type("E", (), {"vectorize": False}),
            }),
        })()

    def _ensure_heavy(self) -> None:
        return None

    def _conversation_model(self) -> str:
        return "fake-model"

    def _begin_chat_turn(self, thread_id, user_id, module, agent_id, user_text,
                         title=None):
        from careercrew_api.chat_lifecycle import begin_turn

        try:
            return begin_turn(
                self.conversation_store, thread_id=thread_id, user_id=user_id,
                module=module, agent_id=agent_id, user_text=user_text,
                model=self._conversation_model(), title=title,
            )
        except Exception:
            return None

    def _finish_chat_turn(self, ctx, content, status="completed", metadata=None,
                          input_tokens=None, output_tokens=None, total_tokens=None,
                          langsmith_run_id=None, retrievals=None, tool_calls=None):
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
            pass

    def _fail_chat_turn(self, ctx, exc):
        from careercrew_api.chat_lifecycle import fail_turn

        if ctx is None:
            return
        try:
            fail_turn(self.conversation_store, ctx, exc)
        except Exception:
            pass

    def _cancel_chat_turn(self, ctx):
        from careercrew_api.chat_lifecycle import cancel_turn

        if ctx is None:
            return
        try:
            cancel_turn(self.conversation_store, ctx)
        except Exception:
            pass

    def health_info(self) -> dict:
        return {
            "status": "ok", "model": "fake-model", "embedding": "fake",
            "vector_store": "fake", "ready": True,
        }

    def get_cycle(self, thread_id: str, user_id: str = "u_001"):
        class FakeCycle:
            def __init__(self_inner):
                self_inner.job_matcher = None
                self_inner.resume_advisor = None

            def run_match(self_inner, intent: str) -> str:
                if self_inner.job_matcher:
                    self_inner.job_matcher.run(None)
                return self.match_output

            def run_resume(self_inner, jd_text: str) -> str:
                if self_inner.resume_advisor:
                    self_inner.resume_advisor.run(None)
                return self.resume_output
        return FakeCycle()

    def run_match_stream(self, thread_id: str, user_id: str, intent: str,
                         cb: Callable[[str], None] | None = None,
                         cancel_check: Callable[[], None] | None = None):
        from careercrew_api.chat_lifecycle import StreamResult

        self.last_call = {
            "method": "run_match_stream", "thread_id": thread_id,
            "user_id": user_id, "intent": intent,
        }
        if cancel_check:
            cancel_check()
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="matcher", agent_id="job_matcher", user_text=intent,
        )
        if cb:
            if self.stream_preamble:
                cb(self.stream_preamble)
            cb(self.match_output)
        self._finish_chat_turn(ctx, self.match_output)
        return StreamResult(content=self.match_output, turn=ctx)

    def run_resume_stream(self, thread_id: str, user_id: str, jd_text: str,
                          cb: Callable[[str], None] | None = None,
                          cancel_check: Callable[[], None] | None = None):
        from careercrew_api.chat_lifecycle import StreamResult

        if cancel_check:
            cancel_check()
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="resume", agent_id="resume_advisor",
            user_text=f"按这个 JD 定制简历：{jd_text[:200]}",
        )
        if cb:
            if self.stream_preamble:
                cb(self.stream_preamble)
            cb(self.resume_output)
        self._finish_chat_turn(ctx, self.resume_output)
        return StreamResult(content=self.resume_output, turn=ctx)

    def run_planner_chat_stream(self, thread_id: str, user_id: str, intent: str,
                                cb: Callable[[str], None] | None = None,
                                cancel_check: Callable[[], None] | None = None):
        from careercrew_api.chat_lifecycle import StreamResult

        if cancel_check:
            cancel_check()
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="chat", agent_id="career_planner", user_text=intent,
        )
        if cb:
            if self.stream_preamble:
                cb(self.stream_preamble)
            cb(self.planner_output)
        self._finish_chat_turn(ctx, self.planner_output)
        return StreamResult(content=self.planner_output, turn=ctx)

    def run_knowledge_ask_stream(self, question: str, user_id: str, thread_id: str = "knowledge",
                                 cb: Callable[[str], None] | None = None,
                                 category: str = "",
                                 scope: str = "all",
                                 cancel_check: Callable[[], None] | None = None):
        from careercrew_api.chat_lifecycle import StreamResult

        self.knowledge_ask_scopes.append(scope)
        output = self.knowledge_output_by_user.get(user_id, self.knowledge_output)
        sources = self.knowledge_sources_by_user.get(user_id, self.knowledge_sources)
        if cancel_check:
            cancel_check()
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="knowledge", agent_id="knowledge_advisor",
            user_text=question,
        )
        if cb:
            if self.stream_preamble:
                cb(self.stream_preamble)
            cb(output)
        # T1.4：可选注入观测字段（token/tool_call/retrieval），供 API 断言
        obs = getattr(self, "knowledge_observability", None) or {}
        self._finish_chat_turn(
            ctx, output, metadata={"sources": sources},
            input_tokens=obs.get("input_tokens"),
            output_tokens=obs.get("output_tokens"),
            total_tokens=obs.get("total_tokens"),
            langsmith_run_id=obs.get("langsmith_run_id"),
            retrievals=obs.get("retrievals"),
            tool_calls=obs.get("tool_calls"),
        )
        return StreamResult(content=output, sources=sources, turn=ctx)

    def record_thread_messages(self, user_id: str, thread_id: str,
                               user_text: str, agent_text: str,
                               module: str = "chat",
                               sources: list[dict] | None = None,
                               metadata: dict | None = None) -> int:
        n = 0
        if user_text:
            self.memory_db.insert_episodic(
                user_id, thread_id, f"t-{thread_id}-{n}", None,
                "user_message", user_text, "",
            )
            n += 1
        if agent_text:
            content: dict | str = agent_text
            if sources or metadata:
                stored = {"text": agent_text}
                if sources:
                    stored["sources"] = sources
                if metadata:
                    stored.update(metadata)
                content = stored
            self.memory_db.insert_episodic(
                user_id, thread_id, f"t-{thread_id}-{n}", None,
                "agent_response", content, "",
            )
            n += 1
        return n

    def record_user_message(self, user_id: str, thread_id: str, user_text: str,
                            module: str = "chat") -> str | None:
        if not user_text:
            return None
        self.memory_db.insert_episodic(
            user_id, thread_id, f"u-{thread_id}", None,
            "user_message", user_text, "",
        )
        return f"u-{thread_id}"

    def new_job_matcher(self, cb: Callable[[str], None] | None = None, episodic=None):
        class FakeAgent:
            def __init__(self_inner):
                self_inner.last_result = type("R", (), {"content": self.match_output})()

            def run(self_inner, state):
                if cb:
                    cb(self.match_output)
        return FakeAgent()

    def new_resume_advisor(self, cb: Callable[[str], None] | None = None, episodic=None):
        class FakeAgent:
            def __init__(self_inner):
                self_inner.last_result = type("R", (), {"content": self.resume_output})()

            def run(self_inner, state):
                if cb:
                    cb(self.resume_output)
        return FakeAgent()

    def new_interviewer(self, cb: Callable[[str], None] | None = None, episodic=None, prompt_path=None):
        class FakeAgent:
            def __init__(self_inner):
                self_inner.last_result = type("R", (), {"content": self.interview_output})()

            def run(self_inner, state):
                if cb:
                    if self.stream_preamble:
                        cb(self.stream_preamble)
                    cb(self.interview_output)
        return FakeAgent()

    def new_consult_agent(self, name: str, cb: Callable[[str], None] | None = None, episodic=None):
        output = self.consult_opinions.get(name, "无意见")

        class FakeAgent:
            def __init__(self_inner):
                self_inner.last_result = type("R", (), {"content": output})()

            def run(self_inner, state):
                if cb:
                    cb(output)
        return FakeAgent()

    def _get_episodic(self, thread_id: str, user_id: str = "u_001"):
        return None  # FakeRuntime 不需要真实 episodic

    def get_threads(self, user_id: str = "u_001", module: str | None = None) -> list[dict]:
        rows = self.thread_store.list(user_id, module=module)
        return [
            {
                "thread_id": r["thread_id"],
                "title": r["title"],
                "module": r["module"],
                "pinned": r["pinned"],
                "retrieval_scope": r.get("retrieval_scope"),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "entries": 0,
            }
            for r in rows
        ]

    def register_thread(self, thread_id: str, user_id: str = "u_001",
                        module: str = "chat", title: str = "",
                        retrieval_scope: dict | None = None) -> dict:
        return self.thread_store.upsert(
            user_id, thread_id, title=title, module=module,
            retrieval_scope=retrieval_scope,
        )

    def touch_thread(self, thread_id: str, user_id: str = "u_001", title: str | None = None,
                     pinned: bool | None = None, module: str | None = None,
                     retrieval_scope: dict | None = None) -> dict:
        from careercrew_api.runtime import ResourceNotFoundError

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

    def delete_thread(self, thread_id: str, user_id: str = "u_001") -> dict:
        from careercrew_api.runtime import ResourceNotFoundError

        if self.thread_store.get(user_id, thread_id) is None:
            raise ResourceNotFoundError(f"thread not found: {thread_id}")
        n = self.thread_store.delete_all_for_thread(user_id, thread_id)
        return {"deleted": n > 0, "thread_id": thread_id, "removed": n}

    def memory_list(self, user_id: str = "u_001", thread_id: str | None = None,
                    type: str = "") -> list[dict]:
        from careercrew_core.memory.semantic import SemanticFactStore

        facts = [f.model_dump() for f in SemanticFactStore(self.memory_db, user_id).list_facts()]
        rows = self.memory_db.list_episodic(user_id, thread_id=thread_id, type=type or None)
        merged = [{
            "kind": "fact", "id": f["name"], "type": f["type"], "ts": f["modified_at"],
            "content": f["content"], "name": f["name"], "description": f["description"],
            "source": f["source"], "confidence": f["confidence"], "version": f["version"],
        } for f in facts if not type or f["type"] == type]
        for r in rows:
            content = r.get("content")
            extra: dict = {}
            if isinstance(content, dict) and "text" in content:
                extra = {k: v for k, v in content.items() if k != "text"}
                content = content["text"]
            event = {
                "kind": "event", "id": r["id"], "type": r["type"], "ts": r["ts"],
                "parentId": r.get("parent_id"), "content": content,
                "thread_id": r.get("thread_id"),
            }
            event.update(extra)
            merged.append(event)
        merged.sort(key=lambda x: x.get("ts", ""))
        return merged

    def memory_delete(self, user_id: str = "u_001", kind: str = "",
                      name: str | None = None, entry_id: str | None = None,
                      thread_id: str | None = None, type: str = "") -> int:
        removed = 0
        if kind in ("", "fact") and name:
            from careercrew_core.memory.semantic import SemanticFactStore

            removed += SemanticFactStore(self.memory_db, user_id).delete_fact(name)
        if kind in ("", "event"):
            removed += self.memory_db.delete_episodic(
                user_id, entry_id=entry_id, thread_id=thread_id, type=type or None
            )
        return removed

    def memory_policy_get(self, user_id: str = "u_001") -> dict:
        g = self.policy_store.global_policy()
        u = self.policy_store.user_policy(user_id)
        return {
            "global": g.model_dump(exclude={"user_id"}),
            "user": u.model_dump(),
            "effective": self.policy_store.effective(user_id, False).model_dump(),
        }

    def memory_policy_set(self, user_id: str = "u_001", enabled: bool | None = None,
                          generate: bool | None = None, use: bool | None = None) -> dict:
        self.policy_store.set_user(user_id, enabled=enabled, generate=generate, use=use)
        return self.memory_policy_get(user_id)

    def memory_settings_get(self) -> dict:
        g = self.policy_store.global_policy()
        return {
            "enabled": bool(g.enabled),
            "feature_enabled": False,
            "global": g.model_dump(exclude={"user_id"}),
            "router_top_n": 5,
            "max_inject_tokens": 2000,
        }

    def memory_settings_set(self, enabled: bool | None = None,
                            generate: bool | None = None, use: bool | None = None) -> dict:
        self.policy_store.set_global(enabled=bool(enabled) if enabled is not None else False,
                                     generate=generate, use=use)
        return self.memory_settings_get()

    def memory_consolidate(self, user_id: str = "u_001", force: bool = False) -> dict:
        from careercrew_core.memory.consolidation import Consolidator

        return Consolidator(self.memory_db, min_sessions=1).consolidate(user_id, force=force)

    @property
    def llm(self):
        """假 LLM：第一轮返回会诊调度决策，之后返回最终答案。"""
        class FakeLLM:
            def invoke(self_inner, prompt, config=None):
                outer = self
                if outer.orchestrator_override:
                    return outer.orchestrator_override(prompt, config)
                outer._orchestrator_calls += 1
                if outer._orchestrator_calls == 1:
                    content = (
                        '{"next_agents": ["salary_negotiator", "career_planner"], '
                        '"tasks": {}, "final_answer": ""}'
                    )
                else:
                    content = (
                        '{"next_agents": [], "tasks": {}, "final_answer": "'
                        + outer.consult_synthesis.replace('"', "'")
                        + '"}'
                    )
                return type("R", (), {"content": content})()
        return FakeLLM()

    def score_answer(self, question: str, answer: str, max_score: int = 10) -> dict:
        return self.score_result

    def record_interview_qa(self, user_id: str, thread_id: str, entries: list[dict]) -> int:
        return len(entries)

    def read_image(self, path: str) -> str:
        if self.upload_error:
            raise self.upload_error
        return self.upload_content

    def load_document(self, path: str, output_dir: str | None = None) -> str:
        if self.upload_error:
            raise self.upload_error
        return self.upload_content

    def ingest_document(
        self,
        path: str,
        user_id: str,
        metadata: dict | None = None,
        progress_cb: Callable[[str, float], None] | None = None,
        category: str = "",
        output_dir: str | None = None,
        doc_name: str = "",
        visibility: str = "private",
    ) -> dict:
        from pathlib import Path

        self.ingest_calls.append({"path": path, "user_id": user_id,
                                  "output_dir": output_dir, "doc_name": doc_name,
                                  "visibility": visibility})
        if self.ingest_error:
            raise self.ingest_error
        if progress_cb:
            progress_cb("vectorize", 0.6)
            progress_cb("store", 0.95)
        doc_id = Path(path).stem
        self.knowledge_docs_by_user.setdefault(user_id, []).append({
            "doc": doc_id, "source": path, "points": 2,
            "owner_user_id": user_id, "visibility": visibility,
        })
        return {"doc_id": doc_id, "points": 2, "path": path}

    def delete_document(self, user_id: str, doc_id: str, is_admin: bool = False) -> tuple[int, bool]:
        visible = [
            (owner, d) for owner, docs in self.knowledge_docs_by_user.items()
            for d in docs
            if d.get("doc") == doc_id
            and (d.get("visibility", "private") == "public" or owner == user_id)
        ]
        if not visible:
            return 0, False
        if any(d.get("visibility") == "public" for _o, d in visible) and not is_admin:
            return 0, True
        deleted = 0
        for owner, d in visible:
            docs = self.knowledge_docs_by_user.get(owner, [])
            if d in docs:
                docs.remove(d)
                deleted += int(d.get("points", 0))
        return deleted, False

    def publish_document(self, user_id: str, doc_id: str) -> int:
        n = 0
        for d in self.knowledge_docs_by_user.get(user_id, []):
            if d.get("doc") == doc_id:
                d["visibility"] = "public"
                n += int(d.get("points", 0))
        return n

    def unpublish_document(self, user_id: str, doc_id: str) -> int:
        n = 0
        for d in self.knowledge_docs_by_user.get(user_id, []):
            if d.get("doc") == doc_id:
                d["visibility"] = "private"
                n += int(d.get("points", 0))
        return n

    def knowledge_status(self, user_id: str, scope: str = "all") -> dict:
        all_docs: list[dict] = []
        for owner, docs in self.knowledge_docs_by_user.items():
            for doc in docs:
                entry = dict(doc)
                entry.setdefault("owner_user_id", owner)
                entry.setdefault("visibility", "private")
                all_docs.append(entry)
        if scope == "public":
            all_docs = [d for d in all_docs if d["visibility"] == "public"]
        elif scope == "private":
            all_docs = [d for d in all_docs if d["owner_user_id"] == user_id]
        else:
            all_docs = [
                d for d in all_docs
                if d["visibility"] == "public" or d["owner_user_id"] == user_id
            ]
        return {"points": sum(int(d.get("points", 0)) for d in all_docs), "docs": all_docs}

    def knowledge_asset_owned(self, user_id: str, path: str) -> bool:
        if not self.knowledge_asset_owners:
            return user_id == "u_001"
        return self.knowledge_asset_owners.get(path) == user_id

    def consult_stream(self, names: list[str], question: str, user_id: str,
                       cb: Callable[[str, str], None] | None = None):
        if cb:
            for name in names:
                cb(name, self.consult_opinions.get(name, "无意见"))
        return {"opinions": self.consult_opinions, "synthesis": self.consult_synthesis}



@pytest.fixture
def fake_runtime() -> FakeRuntime:
    return FakeRuntime()


# ── 跨用户隔离测试基础设施（T0.3） ──
#
# ``tenant_api`` 提供真实认证链（AuthService + FakeAccountStore）下的三账号客户端：
#   - alice : admin（首个管理员，同时作为跨用户隔离测试里的“用户 A”）
#   - bob   : user（“用户 B”）
#   - carol : quality_reviewer（API 级边界断言用）
# 每家产出一个 access-token 头，并完成新建用户的强制改密，使业务 API 放行。
# Runtime 用 FakeRuntime 注入（duck-typed，不触发重组件初始化），鉴权依赖仍是真实的。

TENANT_PASSWORD = "correct-horse-battery-staple"
TENANT_MEMBER_PASSWORD = "member-password-123"
TENANT_JWT_SECRET = "cross-user-isolation-test-signing-secret-with-enough-entropy"


def build_tenant_client(tmp_path, monkeypatch, *, quality_reviewer: str = "carol"):
    """构造三账号 TestClient；返回 (client, runtime, headers, ids)。

    对齐既有 test_tenant_isolation_api.py 的构建模式，但把副本收敛到一处，
    后续隔离测试直接复用本 helper / ``tenant_api`` fixture。
    """
    from fastapi.testclient import TestClient

    from careercrew_api.auth.dependencies import get_auth_service
    from careercrew_api.auth.service import AuthService
    from careercrew_api.deps import get_runtime_dep
    from careercrew_api.main import create_app
    from careercrew_api.routers import knowledge
    from careercrew_core.state.settings import AuthSettings
    from tests.fakes import FakeAccountStore

    # 上传落盘改到临时目录，避免污染 data/uploads（知识库路由按模块属性引用根目录）
    monkeypatch.setattr(knowledge, "_DATA_ROOT", tmp_path)
    from careercrew_api import storage
    from careercrew_api.storage import layout

    monkeypatch.setattr(storage, "L", layout(tmp_path / "data"))

    auth = AuthService(
        AuthSettings(environment="test", jwt_secret=TENANT_JWT_SECRET),
        FakeAccountStore(),
    )
    runtime = FakeRuntime()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_runtime_dep] = lambda: runtime
    client = TestClient(app)

    alice = client.post(
        "/api/auth/bootstrap",
        json={"username": "alice", "password": TENANT_PASSWORD},
    ).json()
    alice_login = client.post(
        "/api/auth/token",
        json={"username": "alice", "password": TENANT_PASSWORD},
    ).json()
    alice_headers = {"Authorization": f"Bearer {alice_login['access_token']}"}

    def _member(username: str, role: str):
        created = client.post(
            "/api/auth/users",
            json={"username": username, "password": TENANT_MEMBER_PASSWORD, "role": role},
            headers=alice_headers,
        )
        assert created.status_code == 201, created.text
        login = client.post(
            "/api/auth/token",
            json={"username": username, "password": TENANT_MEMBER_PASSWORD},
        ).json()
        # 新建用户带强制改密标记：先改密，业务 API 才放行
        change = client.post(
            "/api/auth/password",
            json={"new_password": TENANT_MEMBER_PASSWORD},
            headers={"Authorization": f"Bearer {login['access_token']}"},
        )
        assert change.status_code == 200
        relogin = client.post(
            "/api/auth/token",
            json={"username": username, "password": TENANT_MEMBER_PASSWORD},
        ).json()
        return {"Authorization": f"Bearer {relogin['access_token']}"}, relogin["user"]

    bob_headers, bob_user = _member("bob", "user")
    reviewer_headers, reviewer_user = _member(quality_reviewer, "quality_reviewer")

    headers = {
        "alice": alice_headers,
        "bob": bob_headers,
        "quality_reviewer": reviewer_headers,
    }
    ids = {
        "alice": alice["id"],
        "bob": bob_user["id"],
        "quality_reviewer": reviewer_user["id"],
    }
    return client, runtime, headers, ids


@pytest.fixture
def tenant_api(tmp_path, monkeypatch):
    """跨用户隔离测试的共享双/三账号客户端（真实认证 + FakeRuntime）。"""
    return build_tenant_client(tmp_path, monkeypatch)


@pytest.fixture
def client(fake_runtime: FakeRuntime):
    """TestClient with FakeRuntime injected via dependency_overrides."""
    from fastapi.testclient import TestClient

    from careercrew_api.auth.dependencies import get_current_user
    from careercrew_api.deps import get_runtime_dep
    from careercrew_api.main import create_app

    app = create_app()
    app.dependency_overrides[get_runtime_dep] = lambda: fake_runtime
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u_001", "username": "test-admin", "role": "admin",
    }
    return TestClient(app)
