
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

from careercrew_api.runtime.common import (
    RuntimeInitError,
    logger,
)
from careercrew_core.tracing.langsmith import (
    configure_langsmith,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from careercrew_core.workflow.job_cycle import JobCycle


pass




class HeavyInitMixin:
    """重组件惰性初始化：轻量存储层与 AI 重组件两级分离。"""

    def __init__(self) -> None:
        self._initialized = False
        self._lock = threading.Lock()
        self._stores_ready = False
        self._stores_lock = threading.Lock()
        self._encode_lock = threading.Lock()
        self._um_locks: dict[str, threading.Lock] = {}
        self._um_locks_guard = threading.Lock()
        self._cycles: OrderedDict[tuple[str, str], JobCycle] = OrderedDict()
        self._cycles_lock = threading.Lock()
        self._max_cycles = 32

        # 轻量存储层（_ensure_stores 后填充；纯 Postgres，不依赖 AI 栈）
        self.settings = None
        self.memory_db = None
        self.jobs_store = None       # 岗位库（search_jobs 缓存层，采集器写入）
        self.policy_store = None      # 治理策略（全局 + 用户级）
        self.thread_store = None      # 线程元数据
        self.conversation_store = None  # 对话核心存储（Phase 1 Source of Truth）
        self.attachment_store = None   # 会话附件存储（Phase 3）

        # 重组件（_ensure_heavy 后填充）
        self.llm: BaseChatModel | None = None
        self.embedding = None
        self.store = None
        self.reranker = None
        self.multimodal_search = None
        self.ingest_pipeline = None
        self.memory_router = None     # LLM 记忆路由
        self.memory_injector = None   # 自动注入
        self._episodic_vector_store = None

    # ── 重组件初始化 ──

    def _ensure_stores(self) -> None:
        """轻量初始化：settings + Postgres 存储层（无 numpy/torch/Qdrant/LLM）。

        会话管理类端点（threads 列表/历史/清空/删除、memory 列表）只依赖这一层。
        与 _ensure_heavy 分离的目的：AI 栈（embedding/LLM）故障时，会话历史等
        纯 DB 功能仍可用，不被连带打挂。失败统一映射 RuntimeInitError（503）。
        """
        if self._stores_ready:
            return
        # 兼容测试注入约定：_initialized=True 表示存储已由外部装配（Fake*），
        # 不得用真实 Postgres 存储层覆盖。
        if self._initialized:
            self._stores_ready = True
            return
        with self._stores_lock:
            if self._stores_ready:
                return
            try:
                from careercrew_core.conversation.attachments import (
                    AttachmentStore,
                    create_attachment_db,
                )
                from careercrew_core.conversation.db import create_conversation_db
                from careercrew_core.conversation.store import ConversationStore
                from careercrew_core.jobs import create_jobs_store
                from careercrew_core.memory.db import create_memory_db
                from careercrew_core.memory.policy import MemoryPolicyStore
                from careercrew_core.memory.threads import ThreadStore
                from careercrew_core.state.settings import load_settings

                settings = load_settings()
                memory_db = create_memory_db(settings)

                self.settings = settings
                self.memory_db = memory_db
                self.jobs_store = create_jobs_store(settings)
                self.policy_store = MemoryPolicyStore(memory_db)
                self.thread_store = ThreadStore(memory_db)
                # 对话核心存储（conversation 表 Source of Truth，Postgres/Fake）
                self.conversation_store = ConversationStore(create_conversation_db(settings))
                # 会话附件存储（chat_attachments 表，与 conversation 同库）
                self.attachment_store = AttachmentStore(create_attachment_db(settings))
                self._stores_ready = True
            except Exception as e:
                logger.exception("轻量存储层初始化失败")
                raise RuntimeInitError(
                    f"数据存储初始化失败，请检查数据库连接后重试（{type(e).__name__}: {e}）"
                ) from e

    def _ensure_heavy(self) -> None:
        """惰性初始化重组件（首调 10-30s）。任何失败统一映射 503（RuntimeInitError），
        不再以裸异常形式漏成 500「服务器内部错误」。"""
        # 已完全初始化（含测试注入 fake 的场景）时不做任何事，保持原 _ensure_heavy 语义。
        if self._initialized:
            return
        self._ensure_stores()
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            try:
                self._init_heavy_locked()
                self._initialized = True
            except RuntimeInitError:
                raise
            except Exception as e:
                logger.exception("重组件初始化失败")
                raise RuntimeInitError(
                    f"AI 服务初始化失败，请重启后端后重试（{type(e).__name__}: {e}）"
                ) from e

    def _init_heavy_locked(self) -> None:
        """重组件装配本体（调用方持有 self._lock）。仅装配 AI 栈，DB 存储层复用
        _ensure_stores 的产物，避免同一批连接初始化两遍。"""
        from careercrew_ai.embedding import create_embedding
        from careercrew_ai.llm import create_llm
        from careercrew_ai.reranker.siliconflow_vl_reranker import SiliconFlowVLReranker
        from careercrew_ai.vector_store import create_vector_store
        from careercrew_core.memory.injection import MemoryInjector
        from careercrew_core.memory.router import MemoryRouter
        from careercrew_core.rag.pipeline_multimodal import MultimodalIngestionPipeline
        from careercrew_core.rag.retrieval.multimodal_search import MultimodalSearch

        settings = self.settings
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

        memory_router = MemoryRouter(llm=llm, top_n=settings.memory.router.top_n)
        memory_injector = MemoryInjector(
            db=self.memory_db,
            policy_store=self.policy_store,
            router=memory_router,
            feature_enabled=settings.memory.enabled,
            max_inject_tokens=settings.memory.router.max_inject_tokens,
        )

        self.embedding = embedding
        self.store = store
        self.llm = llm
        self.reranker = rr
        self.multimodal_search = hs
        self.memory_router = memory_router
        self.memory_injector = memory_injector

    # ── 会话级 JobCycle（LRU 缓存）──

    def _get_episodic(self, thread_id: str, user_id: str):
        """获取 per-thread 情景记忆（统一 Postgres/Fake 后端，行按 user_id 隔离）。"""
        from careercrew_core.memory.episodic import EpisodicMemory

        return EpisodicMemory(self.memory_db, user_id=user_id, thread_id=thread_id)

    # ── 对话 run 生命周期（Phase 1：conversation 表 Source of Truth）──
