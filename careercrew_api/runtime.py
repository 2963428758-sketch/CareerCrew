"""运行时单例（§2）：重组件进程级单例 + 会话级 agent/JobCycle。

核心决策：
- 重组件（llm/embedding/store/reranker/MultimodalSearch/memory db）进程级单例
- agent 与 JobCycle 按会话(thread_id)新建（``BaseAgent.last_result`` 是可变属性，并发共享会串写）
- embedding.encode 加锁；记忆 db 写操作按用户隔离（Postgres 行级 / Fake 内存）
- 记忆子系统：Postgres（生产）统一存情景事件/语义事实/治理策略/线程元数据；
  对话历史只由 LangGraph checkpointer 保存，不再双写 episodic
- 初始化放首请求惰性触发（非 lifespan），uvicorn 秒起

组装逻辑与 ``careercrew_core/workflow/job_cycle.py`` 的 ``JobCycle`` 保持一致（无渲染依赖，streaming=True）。
"""
from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from careercrew_core.tracing.langsmith import (
    attach_run_metadata,
    configure_langsmith,
    traced_call,
)
if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from careercrew_core.workflow.job_cycle import JobCycle


def _norm_path(p: str) -> str:
    return str(p).replace("\\", "/").lower()


def _capture_langsmith_run_id() -> str | None:
    """取当前 LangSmith 根 run id（tracing 关闭时为 None）。

    仅在 traced 上下文内有效：traced_call 包住 impl 后，get_current_run_tree()
    返回当前 run 树；tracing 未启用 get_current_run_tree() 仍可安全调用（返回 None）。
    """
    try:
        from langsmith import get_current_run_tree

        tree = get_current_run_tree()
        return str(tree.id) if tree is not None else None
    except Exception:  # noqa: BLE001 - 埋点失败不影响主链路
        return None


def _observability_from_result(result) -> dict:
    """从 AgentResult 抽取观测字段（tokens + tool_call 明细）。

    返回 {input_tokens, output_tokens, total_tokens, tool_calls}；result 为 None
    或缺新字段时相应值为 None / []（静默降级，不阻塞收尾）。
    """
    if result is None:
        return {
            "input_tokens": None, "output_tokens": None, "total_tokens": None,
            "tool_calls": [],
        }
    input_tokens = getattr(result, "input_tokens", None)
    output_tokens = getattr(result, "output_tokens", None)
    total_tokens = None
    if input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    details = getattr(result, "tool_call_details", None) or []
    tool_calls = []
    for d in details:
        err = d.get("error")
        error_type = None
        if err:
            error_type = str(err).split(":", 1)[0] or None
        tool_calls.append({
            "tool_name": str(d.get("name") or ""),
            "input_redacted": d.get("args"),
            "output_summary": None,
            "status": "failed" if err else "completed",
            "duration_ms": d.get("duration_ms"),
            "error_type": error_type,
            "error_summary": err,
        })
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "tool_calls": tool_calls,
    }


def _rag_query_retrievals(tool_call_details: list[dict], start_index: int = 0) -> list[dict]:
    """从 tool_call_details 里 name=="rag_query" 的条目生成 retrieval 行（尽力而为）。

    无法从工具结果拿到 doc/chunk id 与 score（rag_query 返回纯文本），此处只落
    query_text_redacted（args 摘要）+ scope；document_id/chunk_id/recall_score 为空。
    """
    retrievals: list[dict] = []
    idx = start_index
    for d in tool_call_details or []:
        if d.get("name") != "rag_query":
            continue
        args = d.get("args") or {}
        q = args.get("query") if isinstance(args, dict) else None
        retrievals.append({
            "query_index": idx,
            "query_text_redacted": str(q) if q else None,
            "scope": None,
            "document_id": None,
            "chunk_id": None,
            "recall_score": None,
            "used_in_final_context": False,
            # 非 sink 观测路径的 rag_query 均为 Agent 自动检索（无强制上下文），
            # 显式标 'auto'，不依赖 finish_turn 的默认值兜底。
            "retrieval_source": "auto",
        })
        idx += 1
    return retrievals


def _read_image_paths(result) -> set[str]:
    """agent 实际 read_image 过的图片路径（这些来源确实被用来作答）。"""
    paths: set[str] = set()
    for it in getattr(result, "iterations", None) or []:
        for tc in getattr(it, "tool_calls", None) or []:
            if tc.get("name") == "read_image":
                p = (tc.get("args") or {}).get("image_path")
                if p:
                    paths.add(_norm_path(p))
    return paths


def _cap_sources(
    sources: list[dict],
    limit: int = 3,
    min_score: float = 0.1,
    keep_paths: set[str] | None = None,
) -> list[dict]:
    """知识库问答来源收敛：按分数降序取前 limit 条（默认 top-3）。

    低相关度（score < min_score）的来源不展示，除非它的图片被 agent
    实际 read_image 读过（该来源确实支撑了回答，标记 used_image=True）。
    """
    keep = keep_paths or set()
    kept: list[dict] = []
    for s in sources:
        score = float(s.get("score") or 0.0)
        img = _norm_path(s.get("image_path") or "")
        if img and img in keep:
            kept.append({**s, "used_image": True})
        elif score >= min_score:
            kept.append({**s, "used_image": False})
    kept.sort(key=lambda s: float(s.get("score") or 0.0), reverse=True)
    return kept[:limit]


class RuntimeInitError(RuntimeError):
    """运行时初始化失败（重组件加载 / 向量库连接失败等），应映射为 503。"""


class ResourceNotFoundError(LookupError):
    """Authenticated tenant does not own the requested resource."""


class RegenerateConflictError(Exception):
    """regenerate 前置校验失败（非 assistant / 非 completed / 非最后一条 / 不支持的模块）。

    路由映射为 409（区别于 ResourceNotFoundError 的 404）。
    """


class CareerCrewRuntime:
    """进程级重组件单例 + 会话级 agent/JobCycle 工厂。"""

    def __init__(self) -> None:
        self._initialized = False
        self._lock = threading.Lock()
        self._encode_lock = threading.Lock()
        self._um_locks: dict[str, threading.Lock] = {}
        self._um_locks_guard = threading.Lock()
        self._cycles: OrderedDict[tuple[str, str], "JobCycle"] = OrderedDict()
        self._cycles_lock = threading.Lock()
        self._max_cycles = 32

        # 重组件（_ensure_heavy 后填充）
        self.settings = None
        self.llm: "BaseChatModel | None" = None
        self.embedding = None
        self.store = None
        self.reranker = None
        self.multimodal_search = None
        self.ingest_pipeline = None
        self.memory_db = None
        self.episodic = None          # 默认（u_001 / m1）情景记忆
        self.fact_store = None        # 语义事实
        self.policy_store = None      # 治理策略（全局 + 用户级）
        self.thread_store = None      # 线程元数据
        self.memory_router = None     # LLM 记忆路由
        self.memory_injector = None   # 自动注入
        self._episodic_vector_store = None
        self.conversation_store = None  # 对话核心存储（Phase 1 Source of Truth）
        self.attachment_store = None   # 会话附件存储（Phase 3）

    # ── 重组件初始化 ──

    def _ensure_heavy(self) -> None:
        """惰性初始化重组件（首调 10-30s）。初始化失败异常映射 503（RuntimeInitError）。"""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            from pathlib import Path

            from careercrew_ai.embedding import create_embedding
            from careercrew_ai.llm import create_llm
            from careercrew_ai.reranker.siliconflow_vl_reranker import SiliconFlowVLReranker
            from careercrew_ai.vector_store import create_vector_store
            from careercrew_core.memory.db import create_memory_db
            from careercrew_core.memory.episodic import EpisodicMemory
            from careercrew_core.memory.injection import MemoryInjector
            from careercrew_core.memory.policy import MemoryPolicyStore
            from careercrew_core.memory.router import MemoryRouter
            from careercrew_core.memory.semantic import SemanticFactStore
            from careercrew_core.memory.threads import ThreadStore
            from careercrew_core.rag.pipeline_multimodal import MultimodalIngestionPipeline
            from careercrew_core.rag.retrieval.multimodal_search import MultimodalSearch
            from careercrew_core.state.settings import load_settings
            settings = load_settings()
            self.settings = settings
            configure_langsmith(settings)  # 必须先于 create_llm/任何 LLM 调用

            try:
                embedding = create_embedding(settings)
                store = create_vector_store(settings)
            except Exception as e:
                if "DataDirLocked" in type(e).__name__ or "DataDirLocked" in str(e):
                    raise RuntimeInitError(
                        "向量库初始化失败（数据目录被占用或 Qdrant 连接不可用）。"
                        "请检查 Qdrant 服务与 data/db 占用后重试。"
                    ) from e
                raise

            llm = create_llm(settings, max_tokens=1024)
            rr = SiliconFlowVLReranker(settings)
            hs = MultimodalSearch(
                embedding, store, reranker=rr, top_m=30, image_reader=self.read_image
            )

            pipe = MultimodalIngestionPipeline(
                embedding, store, contextual=False,
                output_dir=settings.rag.loaders.output_dir,
                loader_provider=settings.rag.loaders.provider,
                loader_api_key=settings.rag.loaders.api_key,
                loader_device=settings.rag.loaders.device,
                loader_method=settings.rag.loaders.method,
                loader_formula=settings.rag.loaders.formula,
                loader_table=settings.rag.loaders.table,
                loader_language=settings.rag.loaders.language,
                loader_model_version=settings.rag.loaders.model_version,
                loader_poll_interval=settings.rag.loaders.poll_interval,
                loader_timeout=settings.rag.loaders.timeout,
                chunk_size=settings.rag.chunking.chunk_size,
                chunk_overlap=settings.rag.chunking.chunk_overlap,
            )
            self.ingest_pipeline = pipe

            # 知识库只经由上传端点显式入库（历史首启扫描已移除：简历原件不得自动入知识库）

            memory_db = create_memory_db(settings)
            episodic = EpisodicMemory(memory_db, user_id="u_001", thread_id="m1")
            fact_store = SemanticFactStore(memory_db, user_id="u_001")
            policy_store = MemoryPolicyStore(memory_db)
            thread_store = ThreadStore(memory_db)
            memory_router = MemoryRouter(
                llm=llm, top_n=settings.memory.router.top_n
            )
            memory_injector = MemoryInjector(
                db=memory_db,
                policy_store=policy_store,
                router=memory_router,
                episodic=episodic,
                feature_enabled=settings.memory.enabled,
                max_inject_tokens=settings.memory.router.max_inject_tokens,
            )

            self.embedding = embedding
            self.store = store
            self.llm = llm
            self.reranker = rr
            self.multimodal_search = hs
            self.memory_db = memory_db
            # 对话核心存储（conversation 表 Source of Truth，Postgres/Fake）
            from careercrew_core.conversation.db import create_conversation_db
            from careercrew_core.conversation.store import ConversationStore

            self.conversation_store = ConversationStore(create_conversation_db(settings))
            # 会话附件存储（chat_attachments 表，与 conversation 同库）
            from careercrew_core.conversation.attachments import (
                AttachmentStore,
                create_attachment_db,
            )

            self.attachment_store = AttachmentStore(create_attachment_db(settings))
            self.episodic = episodic
            self.fact_store = fact_store
            self.policy_store = policy_store
            self.thread_store = thread_store
            self.memory_router = memory_router
            self.memory_injector = memory_injector
            self._initialized = True

    # ── 会话级 JobCycle（LRU 缓存）──

    def _get_episodic(self, thread_id: str, user_id: str):
        """获取 per-thread 情景记忆（统一 Postgres/Fake 后端，行按 user_id 隔离）。"""
        from careercrew_core.memory.episodic import EpisodicMemory

        return EpisodicMemory(self.memory_db, user_id=user_id, thread_id=thread_id)

    # ── 对话 run 生命周期（Phase 1：conversation 表 Source of Truth）──

    def _conversation_model(self) -> str:
        """当前 run 的 model（settings.llm.model；未初始化时退化空串）。"""
        if self.settings is None:
            return ""
        return getattr(self.settings.llm, "model", "") or ""

    def _begin_chat_turn(self, thread_id: str, user_id: str, module: str,
                         agent_id: str, user_text: str, title: str | None = None,
                         user_metadata: dict | None = None):
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
            return begin_turn(
                self.conversation_store,
                thread_id=thread_id, user_id=user_id, module=module,
                agent_id=agent_id, user_text=user_text,
                model=self._conversation_model(), title=title,
                prompt_version=prompt_version_for_agent(agent_id),
                agent_version=agent_version(),
                user_metadata=user_metadata,
            )
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
        existing = ts.get(user_id, thread_id)
        if existing is None:
            ts.upsert(user_id, thread_id, title=title[:50], module=module)
        elif title and not existing.get("title"):
            ts.upsert(user_id, thread_id, title=title[:50], module=module,
                      pinned=bool(existing.get("pinned")))

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
        """写会话 transcript（user_message + agent_response）到情景记忆，供 /api/memory 恢复。

        前端按 thread_id 从 /api/memory 恢复对话；本方法把一轮 user/agent 消息
        追加到该 thread 的 episodic（append-only 链）。
        sources（知识库依据来源）与 metadata（如会诊调度过程）随 agent_response
        一起存储，刷新后可恢复。
        """
        self._ensure_heavy()
        from careercrew_core.memory.redaction import redact_secrets
        from careercrew_core.memory.types import MemoryEntry

        self._ensure_thread(thread_id, user_id, module=module, title=user_text[:50])
        ep = self._get_episodic(thread_id, user_id)
        n = 0
        if user_text:
            ep.write(MemoryEntry(
                type="user_message", content=redact_secrets(user_text),
            ))
            n += 1
        if agent_text:
            content: dict | str = redact_secrets(agent_text)
            if sources or metadata:
                stored = {"text": content}
                if sources:
                    stored["sources"] = sources
                if metadata:
                    stored.update(metadata)
                content = stored
            ep.write(MemoryEntry(
                type="agent_response", content=content,
            ))
            n += 1
        return n

    def record_user_message(self, user_id: str, thread_id: str, user_text: str,
                            module: str = "chat") -> str | None:
        """在 agent 运行开始前立即落库用户消息，返回 entry id（供历史加载时跳过）。

        长 agent 运行（知识库检索 / VLM 读图 / 多轮工具调用）可能耗时数分钟，
        若只在运行完成后才写 transcript，运行挂起/失败/进程重启时用户的问题
        就永久丢失（刷新也找不回）。这里先落 user_message，运行结束后再补
        agent_response，保证问题随时可恢复。
        """
        self._ensure_heavy()
        from careercrew_core.memory.redaction import redact_secrets
        from careercrew_core.memory.types import MemoryEntry

        if not user_text:
            return None
        self._ensure_thread(thread_id, user_id, module=module, title=user_text[:50])
        ep = self._get_episodic(thread_id, user_id)
        entry = ep.write(MemoryEntry(
            type="user_message", content=redact_secrets(user_text),
        ))
        return entry.id

    def get_threads(self, user_id: str, module: str | None = None) -> list[dict]:
        """列出用户的所有对话线程（Postgres threads 表，按置顶+更新时间排序）。"""
        self._ensure_heavy()
        return self.thread_store.list(user_id, module=module)

    def register_thread(self, thread_id: str, user_id: str,
                        module: str = "chat", title: str = "",
                        retrieval_scope: dict | None = None) -> dict:
        """登记线程（前端新会话时调用）。"""
        self._ensure_heavy()
        return self.thread_store.upsert(
            user_id, thread_id, title=title, module=module,
            retrieval_scope=retrieval_scope,
        )

    def touch_thread(self, thread_id: str, user_id: str, title: str | None = None,
                     pinned: bool | None = None, module: str | None = None,
                     retrieval_scope: dict | None = None) -> dict:
        """更新线程标题/置顶/检索范围（PATCH）。"""
        self._ensure_heavy()
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
        self._ensure_heavy()
        if self.thread_store.get(user_id, thread_id) is None:
            raise ResourceNotFoundError(f"thread not found: {thread_id}")
        n = self.thread_store.delete_all_for_thread(user_id, thread_id)
        return {"deleted": n > 0, "thread_id": thread_id, "removed": n}

    def get_cycle(self, thread_id: str, user_id: str) -> "JobCycle":
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
                jm, ra, user_model_store=self.fact_store,
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
                         cancel_check: Callable[[], None] | None = None) -> "StreamResult":
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
            cancel_check=cancel_check,
        )

    def _run_match_stream_impl(self, thread_id: str, user_id: str, intent: str,
                               cb: Callable[[str], None] | None = None,
                               mentions: list[dict] | None = None,
                               cancel_check: Callable[[], None] | None = None) -> "StreamResult":
        from careercrew_api.chat_lifecycle import StreamResult

        attach_run_metadata(user_id=user_id, thread_id=thread_id, stage="match")
        ls_run_id = _capture_langsmith_run_id()
        if cancel_check:
            cancel_check()
        user_meta: dict | None = None
        if mentions:
            user_meta = {"mentions": mentions}
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="matcher", agent_id="job_matcher",
            user_text=intent, user_metadata=user_meta,
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
        cycle.job_matcher = self.new_job_matcher(cb, episodic=ep)
        if cancel_check:
            cancel_check()
        try:
            result = cycle.run_match(intent)
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
                          cancel_check: Callable[[], None] | None = None) -> "StreamResult":
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
            cancel_check=cancel_check,
        )

    def _run_resume_stream_impl(self, thread_id: str, user_id: str, jd_text: str,
                                cb: Callable[[str], None] | None = None,
                                mentions: list[dict] | None = None,
                                cancel_check: Callable[[], None] | None = None) -> "StreamResult":
        from careercrew_api.chat_lifecycle import StreamResult

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
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="resume", agent_id="resume_advisor",
            user_text=user_text,
            # T1.6：user content 是截断摘要，完整 jd_text 存 metadata 供 regenerate
            # 忠实重跑（截断至 5000 字符）。
            user_metadata=user_meta,
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
        cycle.resume_advisor = self.new_resume_advisor(cb, episodic=ep)
        if cancel_check:
            cancel_check()
        try:
            result = cycle.run_resume(jd_text)
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
                                cancel_check: Callable[[], None] | None = None) -> "StreamResult":
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
            cancel_check=cancel_check,
        )

    def _run_planner_chat_stream_impl(self, thread_id: str, user_id: str, intent: str,
                                      cb: Callable[[str], None] | None = None,
                                      mentions: list[dict] | None = None,
                                      cancel_check: Callable[[], None] | None = None) -> "StreamResult":
        from careercrew_api.chat_lifecycle import StreamResult

        attach_run_metadata(user_id=user_id, thread_id=thread_id, stage="planning")
        ls_run_id = _capture_langsmith_run_id()
        from langchain_core.messages import HumanMessage

        if cancel_check:
            cancel_check()
        user_meta: dict | None = None
        if mentions:
            user_meta = {"mentions": mentions}
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="chat", agent_id="career_planner",
            user_text=intent, user_metadata=user_meta,
        )
        ep = self._get_episodic(thread_id, user_id)
        agent = self.new_career_planner(cb, episodic=ep)
        try:
            # 先落库用户消息：长工具链（搜岗位/查薪资）中断也不丢问题
            pending_id = self.record_user_message(
                user_id, thread_id, intent, module="chat"
            )
        except Exception:
            pending_id = None
        if cancel_check:
            cancel_check()
        state = {
            "thread_id": thread_id, "user_id": user_id, "stage": "planning",
            "user_intent": intent,
            "messages": [HumanMessage(content=intent)],
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
                                 cancel_check: Callable[[], None] | None = None) -> "StreamResult":
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
        )

    def _run_knowledge_ask_stream_impl(self, question: str, user_id: str,
                                       thread_id: str = "knowledge",
                                       cb: Callable[[str], None] | None = None,
                                       category: str = "",
                                       scope: str = "all",
                                       mentions: list[dict] | None = None,
                                       cancel_check: Callable[[], None] | None = None) -> "StreamResult":
        from careercrew_api.chat_lifecycle import StreamResult

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
        ctx = self._begin_chat_turn(
            thread_id, user_id, module="knowledge", agent_id="knowledge_advisor",
            user_text=question,
            # T1.6：category/scope 存 user metadata，供 regenerate 忠实重跑（同检索范围）。
            # T3.4：mentions 一并记录，供 regenerate 与审计（强制上下文 vs auto 区分）。
            user_metadata=user_meta,
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
            "messages": [HumanMessage(content=question)],
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
            min_score=0.1,
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

    def run_regenerate_stream(self, message_id: str, user_id: str,
                              cb: Callable[[str], None] | None = None,
                              cancel_check: Callable[[], None] | None = None) -> "StreamResult":
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
                                    cancel_check: Callable[[], None] | None = None) -> "StreamResult":
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

            agent = self.new_career_planner(cb, episodic=ep)
            state = {
                "thread_id": thread_id, "user_id": user_id, "stage": "planning",
                "user_intent": question,
                "messages": [HumanMessage(content=question)],
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

            category = meta.get("category") or ""
            scope = meta.get("scope") or "all"
            # 绑定决策：category/scope 缺失时回退到端点自身默认值（""/"all"），
            # 这仍是忠实重跑（等价于首次无参调用），但记录警告便于排查 legacy 行。
            if not meta.get("category") or not meta.get("scope"):
                import logging
                logging.getLogger(__name__).warning(
                    "regenerate: knowledge turn %s missing category/scope metadata, "
                    "falling back to endpoint defaults (category=%r scope=%r)",
                    user_msg.get("turn_id"), category, scope,
                )
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
            )
            state = {
                "thread_id": thread_id, "user_id": user_id, "stage": "knowledge",
                "user_intent": question,
                "messages": [HumanMessage(content=question)],
                "pending_action": None, "agent_outputs": {}, "target_companies": [],
            }
            agent.run(state)
            lr = agent.last_result
            content = (getattr(lr, "content", "") or "").strip()
            capped = _cap_sources(
                sources, limit=3, min_score=0.1,
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

    def _thread_history_messages(self, user_id: str, thread_id: str,
                                 max_rounds: int = 10,
                                 exclude_entry_id: str | None = None) -> list:
        """从 episodic 恢复该线程的历史对话（user_message/agent_response），供多轮上下文。

        只取本线程、按时间序，最多保留最近 max_rounds 轮；内容为 dict 时取 text。
        exclude_entry_id：跳过刚写入的当前用户消息（本轮问题由调用方单独放入 messages），
        避免上下文重复。
        """
        from langchain_core.messages import AIMessage, HumanMessage

        rows = self.memory_db.list_episodic(
            user_id, thread_id=thread_id, type=None
        )
        msgs: list = []
        for r in rows:
            if exclude_entry_id and r.get("id") == exclude_entry_id:
                continue
            if r.get("type") not in ("user_message", "agent_response"):
                continue
            content = r.get("content")
            if isinstance(content, dict) and "text" in content:
                content = content["text"]
            if not content:
                continue
            if r["type"] == "user_message":
                msgs.append(HumanMessage(content=content))
            else:
                msgs.append(AIMessage(content=content))
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
        """从 episodic 恢复该线程历史对话（供 BaseAgent.history_loader）。"""
        try:
            return self._thread_history_messages(
                user_id, thread_id, exclude_entry_id=exclude_entry_id
            )
        except Exception:
            return []

    def _make_tools(self, kind: str, episodic=None, rag_sink=None, rag_category=None,
                    knowledge_access_filters: dict | None = None,
                    forced_doc_ids: list[str] | None = None):
        """构造 agent 工具集；必须显式携带认证用户的 episodic 上下文。"""
        from careercrew_core.memory.semantic import SemanticFactStore
        from careercrew_core.tools.internal.memory_write import make_memory_write_tool
        from careercrew_core.tools.internal.memory_search import make_memory_search_tool
        from careercrew_core.tools.internal.profile_update import make_profile_update_tool
        from careercrew_core.tools.internal.rag_query import make_rag_query_tool
        from careercrew_core.tools.internal.read_image import make_read_image_tool
        from careercrew_core.tools.internal.salary_query import make_salary_query_tool
        from careercrew_core.tools.internal.search_jobs import search_jobs
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
        )
        from careercrew_core.rag.categories import categories_for_agent

        # 每个 agent 的 rag_query 只检索对应分类（knowledge 分支由 rag_category 用户选择控制）
        cats = categories_for_agent(kind)
        if kind == "matcher":
            tools.register(ToolSpec(tool=search_jobs))
            tools.register(ToolSpec(tool=make_rag_query_tool(
                hs, categories=cats, filters={"user_id": user_id},
            )))
            tools.register(ToolSpec(tool=make_memory_write_tool(ep, vi)))
            tools.register(ToolSpec(tool=mem_search))
            tools.register(ToolSpec(tool=make_profile_update_tool(
                SemanticFactStore(self.memory_db, user_id), user_id=user_id,
                source="job_matcher")))
        elif kind == "resume":
            tools.register(ToolSpec(tool=make_rag_query_tool(
                hs, categories=cats, filters={"user_id": user_id},
            )))
            tools.register(ToolSpec(tool=make_profile_update_tool(
                SemanticFactStore(self.memory_db, user_id), user_id=user_id,
                source="resume_advisor")))
        elif kind == "interviewer":
            tools.register(ToolSpec(tool=make_rag_query_tool(
                hs, categories=cats, filters={"user_id": user_id},
            )))
            tools.register(ToolSpec(tool=make_memory_write_tool(ep, vi)))
            tools.register(ToolSpec(tool=mem_search))
        elif kind == "salary":
            tools.register(ToolSpec(tool=make_rag_query_tool(
                hs, categories=cats, filters={"user_id": user_id},
            )))
            tools.register(ToolSpec(tool=make_profile_update_tool(
                SemanticFactStore(self.memory_db, user_id), user_id=user_id,
                source=kind)))
            tools.register(ToolSpec(tool=mem_search))
            tools.register(ToolSpec(tool=make_salary_query_tool()))
        elif kind == "planner":
            # 职业规划师：求职对话页的主理 agent，职责聚焦求职规划
            tools.register(ToolSpec(tool=make_rag_query_tool(
                hs, categories=cats, filters={"user_id": user_id},
            )))
            tools.register(ToolSpec(tool=make_profile_update_tool(
                SemanticFactStore(self.memory_db, user_id), user_id=user_id,
                source="career_planner")))
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
                filters=kf,
            )))
            # 个人背景问题（学校/专业/教育等）常藏在简历页图里，允许顾问按需读图
            tools.register(ToolSpec(tool=make_read_image_tool(
                self.settings,
                path_authorizer=lambda path: self.knowledge_asset_owned(user_id, path),
            )))
            # "我有哪些项目/技能/目标公司" 等个人记忆问题：允许查语义事实 + 情景事件
            tools.register(ToolSpec(tool=mem_search))
        return tools

    def new_job_matcher(self, cb: Callable[[str], None] | None = None, episodic=None):
        self._ensure_heavy()
        from careercrew_core.agents.job_matcher import JobMatcher

        return JobMatcher(
            llm=self.llm, tools=self._make_tools("matcher", episodic=episodic),
            max_iterations=15, stream_callback=cb, memory_injector=self.memory_injector,
            history_loader=self._history_loader,
            compaction=self._compaction_kwargs() or None,
        )

    def new_resume_advisor(self, cb: Callable[[str], None] | None = None, episodic=None):
        self._ensure_heavy()
        from careercrew_core.agents.resume_advisor import ResumeAdvisor

        return ResumeAdvisor(
            llm=self.llm, tools=self._make_tools("resume", episodic=episodic),
            max_iterations=15, stream_callback=cb, memory_injector=self.memory_injector,
            history_loader=self._history_loader,
            compaction=self._compaction_kwargs() or None,
        )

    def new_interviewer(self, cb: Callable[[str], None] | None = None, episodic=None, prompt_path=None):
        self._ensure_heavy()
        from careercrew_core.agents.interviewer import Interviewer

        return Interviewer(
            llm=self.llm, tools=self._make_tools("interviewer", episodic=episodic),
            max_iterations=15, stream_callback=cb, prompt_path=prompt_path,
            memory_injector=self.memory_injector,
            history_loader=self._history_loader,
            compaction=self._compaction_kwargs() or None,
        )

    def new_knowledge_advisor(self, cb: Callable[[str], None] | None = None, episodic=None,
                              rag_sink=None, category: str = "",
                              knowledge_access_filters: dict | None = None,
                              forced_doc_ids: list[str] | None = None):
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
            llm=self.llm,
            tools=self._make_tools(
                "knowledge", episodic=episodic, rag_sink=rag_sink, rag_category=category,
                knowledge_access_filters=knowledge_access_filters,
                forced_doc_ids=forced_doc_ids,
            ),
            max_iterations=15, stream_callback=cb, memory_injector=self.memory_injector,
            history_loader=self._history_loader,
            compaction=self._compaction_kwargs() or None,
            prompt_suffix=prompt_suffix,
        )

    def new_career_planner(self, cb: Callable[[str], None] | None = None, episodic=None):
        """职业规划师（求职对话主理人）：聚焦求职规划，建画像、定目标公司池、做阶段规划与复盘。"""
        self._ensure_heavy()
        from careercrew_core.agents.career_planner import CareerPlanner

        return CareerPlanner(
            llm=self.llm, tools=self._make_tools("planner", episodic=episodic),
            max_iterations=15, stream_callback=cb, memory_injector=self.memory_injector,
            history_loader=self._history_loader,
            compaction=self._compaction_kwargs() or None,
        )

    def new_consult_agent(self, name: str, cb: Callable[[str], None] | None = None, episodic=None):
        """按名字建会诊 agent。"""
        self._ensure_heavy()
        if name == "salary_negotiator":
            from careercrew_core.agents.salary_negotiator import SalaryNegotiator

            return SalaryNegotiator(
                llm=self.llm, tools=self._make_tools("salary", episodic=episodic),
                max_iterations=15, stream_callback=cb, memory_injector=self.memory_injector,
                history_loader=self._history_loader,
                compaction=self._compaction_kwargs() or None,
            )
        if name == "career_planner":
            return self.new_career_planner(cb, episodic=episodic)
        if name == "job_matcher":
            return self.new_job_matcher(cb, episodic=episodic)
        if name == "resume_advisor":
            return self.new_resume_advisor(cb, episodic=episodic)
        if name == "interviewer":
            return self.new_interviewer(cb, episodic=episodic)
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
        return record_interview_qa(episodic, entries, vector_index=vi)

    # ── 记忆管理 API（数据看板 / 治理） ──

    def memory_list(self, user_id: str, thread_id: str | None = None,
                    type: str = "") -> list[dict]:
        """列出语义事实 + 情景事件（可过滤）。"""
        self._ensure_heavy()
        from careercrew_core.memory.semantic import SemanticFactStore

        facts = [f.model_dump() for f in SemanticFactStore(self.memory_db, user_id).list_facts()]
        rows = self.memory_db.list_episodic(user_id, thread_id=thread_id, type=type or None)
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

    def memory_delete(self, user_id: str, kind: str = "",
                      name: str | None = None, entry_id: str | None = None,
                      thread_id: str | None = None, type: str = "") -> int:
        """删除语义事实（kind=fact / name）或情景事件（kind=event / entry_id）。"""
        self._ensure_heavy()
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
        eff = self.policy_store.effective(user_id, self.settings.memory.enabled)
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
        from careercrew_core.memory.consolidation import Consolidator

        c = Consolidator(
            self.memory_db,
            min_interval_hours=self.settings.memory.consolidation.min_interval_hours,
            min_sessions=self.settings.memory.consolidation.min_sessions,
        )
        return c.consolidate(user_id, force=force)

    def read_image(self, path: str) -> str:
        """用视觉模型读图片内容。"""
        self._ensure_heavy()
        from careercrew_core.tools.internal.read_image import make_read_image_tool

        tool = make_read_image_tool(self.settings)
        return tool.invoke({"image_path": path, "prompt": "请描述图片内容并提取其中的文字。"})

    def load_document(self, path: str, output_dir: str | None = None) -> str:
        """MinerU 解析为文本（resume 上传 pdf/docx 等；按 provider 走云端 API 或本地子进程）。

        output_dir：按用户/文档隔离的解析产物目录（默认取 settings.rag.loaders.output_dir）。
        """
        loaders = self.settings.rag.loaders
        out_dir = loaders.output_dir if output_dir is None else output_dir
        if loaders.provider == "local":
            from careercrew_core.rag.loaders.mineru_loader import MinerULoader

            parsed = MinerULoader(
                out_dir,
                device=loaders.device,
                method=loaders.method,
                formula=loaders.formula,
            ).parse(path)
        else:
            from careercrew_core.rag.loaders.mineru_api_loader import MinerUApiLoader

            parsed = MinerUApiLoader(
                out_dir,
                api_key=loaders.api_key,
                model_version=loaders.model_version,
                formula=loaders.formula,
                table=loaders.table,
                language=loaders.language,
                poll_interval=loaders.poll_interval,
                timeout=loaders.timeout,
            ).parse(path)
        return parsed.to_text()

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
        """知识库入库（多模态管线：md 走文本，PDF/图片走 MinerU）。

        progress_cb(stage, progress) 可选进度回调：stage ∈ parse/vectorize/store，
        progress ∈ [0, 1]（阶段边界处的真实进度，非秒级平滑值）。
        category: 内容分类（resume/knowledge/interview）；空串按 doc_name（原文件名）自动识别。
        output_dir: 按用户/文档隔离的解析产物目录。
        visibility: private | public（公共仅管理员上传时指定）。
        """
        self._ensure_heavy()
        from pathlib import Path

        from careercrew_api.storage import DATA_ROOT

        p = Path(path).resolve()
        if not p.is_relative_to(DATA_ROOT.resolve()):
            raise ValueError(f"入库路径越界: {p} 不在 {DATA_ROOT} 内")
        if not category:
            from careercrew_core.rag.categories import category_for_doc

            category = category_for_doc(doc_name or p.stem)
        if visibility not in ("private", "public"):
            raise ValueError(f"invalid visibility: {visibility}")
        owner_metadata = {**(metadata or {}), "owner_user_id": user_id, "visibility": visibility}
        n = self.ingest_pipeline.ingest_file(
            p, metadata=owner_metadata, progress_cb=progress_cb, category=category,
            output_dir=output_dir,
        )
        return {"doc_id": p.stem, "points": n, "path": str(p)}

    def delete_document(self, user_id: str, doc_id: str, is_admin: bool = False) -> tuple[int, bool]:
        """删除知识文档向量点。返回 (deleted, public_blocked)。

        非 admin 只能删本人私有；admin 可额外删除公共条目。
        """
        self._ensure_heavy()
        visible = self.store.list_docs(filters={"__access_user": user_id, "doc": doc_id})
        if not visible:
            return 0, False
        has_public = any(d.get("visibility") == "public" for d in visible)
        if has_public and not is_admin:
            return 0, True
        deleted = self.store.delete_by_metadata(
            {"owner_user_id": user_id, "doc": doc_id, "visibility": "private"}
        )
        if has_public and is_admin:
            deleted += self.store.delete_by_metadata({"doc": doc_id, "visibility": "public"})
        return deleted, False

    def publish_document(self, user_id: str, doc_id: str) -> int:
        self._ensure_heavy()
        return self.store.set_payload_by_filter(
            {"visibility": "public"}, {"owner_user_id": user_id, "doc": doc_id}
        )

    def unpublish_document(self, user_id: str, doc_id: str) -> int:
        self._ensure_heavy()
        return self.store.set_payload_by_filter(
            {"visibility": "private"}, {"owner_user_id": user_id, "doc": doc_id}
        )

    def knowledge_status(self, user_id: str, scope: str = "all") -> dict:
        """知识库状态：总点数 + 文档列表。scope: all（公共+本人私有）/public/private。"""
        self._ensure_heavy()
        docs = self.store.list_docs(filters=self._knowledge_scope_filters(user_id, scope))
        return {"points": sum(int(doc.get("points", 0)) for doc in docs), "docs": docs}

    @staticmethod
    def _knowledge_scope_filters(user_id: str, scope: str) -> dict:
        if scope == "public":
            return {"visibility": "public"}
        if scope == "private":
            return {"owner_user_id": user_id}
        return {"__access_user": user_id}

    def knowledge_asset_owned(self, user_id: str, path: str) -> bool:
        """Verify an image source is visible to this tenant (own private or public)."""
        self._ensure_heavy()
        from careercrew_api.storage import DATA_ROOT

        resolved = Path(path).resolve()
        if not resolved.is_relative_to(DATA_ROOT.resolve()):
            return False
        return bool(self.store.metadata_exists({"__access_user": user_id, "image_path": str(resolved)}))

    # ── Context @ 引用（T3.4 §15）──

    def _resume_library_items(self, user_id: str) -> list[dict]:
        """读取本人简历库条目元数据（data/parsed/resumes/{user_id}/*/meta.json）。"""
        import json as _json

        from careercrew_api.storage import L

        user_dir = L.parsed_resumes / user_id
        items: list[dict] = []
        if user_dir.exists():
            for meta_path in user_dir.glob("*/meta.json"):
                try:
                    meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001 - 元数据损坏时跳过单条
                    continue
                if meta.get("user_id") != user_id:
                    continue
                items.append(meta)
        items.sort(key=lambda m: m.get("created_at", 0), reverse=True)
        return items

    def list_context_resources(self, user_id: str, types: list[str] | None = None,
                               q: str = "") -> list[dict]:
        """§15.1：返回当前用户可引用的资源（本人 private + public 知识 + 本人简历）。

        types 过滤（knowledge/resume，缺省两者）；q 按名称模糊过滤（不区分大小写）。
        返回 §15.1 形状：{"type","id","name","visibility"}。
        """
        self._ensure_heavy()
        ql = (q or "").strip().lower()
        want_knowledge = types is None or "knowledge" in types
        want_resume = types is None or "resume" in types
        items: list[dict] = []

        if want_knowledge:
            # 本人 private + public（与 ask 的 all scope 一致）
            docs = self.store.list_docs(filters=self._knowledge_scope_filters(user_id, "all"))
            for d in docs:
                doc_id = str(d.get("doc") or "")
                if ql and ql not in doc_id.lower():
                    continue
                items.append({
                    "type": "knowledge_document",
                    "id": doc_id,
                    "name": doc_id,
                    "visibility": str(d.get("visibility") or "private"),
                })

        if want_resume:
            for meta in self._resume_library_items(user_id):
                rid = str(meta.get("resume_id") or "")
                name = str(meta.get("filename") or rid)
                if ql and ql not in name.lower() and ql not in rid.lower():
                    continue
                items.append({
                    "type": "resume",
                    "id": rid,
                    "name": name,
                    "visibility": "private",
                })
        return items

    def resolve_mentions(self, user_id: str, mentions: list[dict]) -> list[dict]:
        """服务端再次校验 mentions（§15.2）；不合法抛 MentionRejected。返回 resolved dict 列表。"""
        from careercrew_api.mentions import resolve_mentions as _resolve

        self._ensure_heavy()
        docs = self.store.list_docs(filters=self._knowledge_scope_filters(user_id, "all"))
        resumes = self._resume_library_items(user_id)
        resolved = _resolve(
            user_id, mentions, knowledge_docs=docs, resume_items=resumes,
        )
        return [m.as_dict() for m in resolved]



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


# ── 模块级双检锁惰性单例 ──

_runtime: CareerCrewRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> CareerCrewRuntime:
    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = CareerCrewRuntime()
    return _runtime


def reset_runtime() -> None:
    """测试用：重置单例。"""
    global _runtime
    _runtime = None
