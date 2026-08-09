"""运行时单例（§2）：重组件进程级单例 + 会话级 agent/JobCycle。

核心决策：
- 重组件（llm/embedding/store/reranker/HybridSearch/episodic/user_model）进程级单例
- agent 与 JobCycle 按会话(thread_id)新建（``BaseAgent.last_result`` 是可变属性，并发共享会串写）
- embedding.encode 加锁；user_model 写操作 per-user lock
- 初始化放首请求惰性触发（非 lifespan），uvicorn 秒起

复用 ``careercrew_cli/app.py`` 的 ``_build_job_cycle`` 组装逻辑，去掉 Renderer 依赖。
"""
from __future__ import annotations

import json
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from careercrew_cli.workflow.job_cycle import JobCycle


class RuntimeInitError(RuntimeError):
    """运行时初始化失败（如 Milvus DataDirLocked），应映射为 503。"""


class CareerCrewRuntime:
    """进程级重组件单例 + 会话级 agent/JobCycle 工厂。"""

    def __init__(self) -> None:
        self._initialized = False
        self._lock = threading.Lock()
        self._encode_lock = threading.Lock()
        self._um_locks: dict[str, threading.Lock] = {}
        self._um_locks_guard = threading.Lock()
        self._cycles: OrderedDict[str, "JobCycle"] = OrderedDict()
        self._cycles_lock = threading.Lock()
        self._max_cycles = 32
        self._thread_episodics: dict[str, object] = {}  # per-thread EpisodicMemory

        # 重组件（_ensure_heavy 后填充）
        self.settings = None
        self.llm: "BaseChatModel | None" = None
        self.embedding = None
        self.store = None
        self.reranker = None
        self.hybrid_search = None
        self.episodic = None
        self.user_model = None
        self.tracer = None

    # ── 重组件初始化 ──

    def _ensure_heavy(self) -> None:
        """惰性初始化重组件（首调 10-30s）。捕获 Milvus DataDirLocked -> 503。"""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            from pathlib import Path

            from careercrew_ai.embedding import create_embedding
            from careercrew_ai.llm import create_llm
            from careercrew_ai.reranker import create_reranker
            from careercrew_ai.vector_store import create_vector_store
            from careercrew_core.memory.episodic import EpisodicMemory
            from careercrew_core.memory.user_model import UserModelStore
            from careercrew_core.rag.pipeline import IngestionPipeline
            from careercrew_core.rag.retrieval.hybrid_search import HybridSearch
            from careercrew_core.state.settings import load_settings
            from careercrew_core.tracing.trace import TraceRecorder

            settings = load_settings()
            self.settings = settings

            try:
                embedding = create_embedding(settings)
                store = create_vector_store(settings)
            except Exception as e:
                if "DataDirLocked" in type(e).__name__ or "DataDirLocked" in str(e):
                    raise RuntimeInitError(
                        "Milvus 数据目录被锁（可能有残留进程占用）。"
                        "请结束所有占用 data/db 的进程后重试。"
                    ) from e
                raise

            llm = create_llm(settings, max_tokens=1024)
            rr = create_reranker(settings)
            hs = HybridSearch(embedding, store, reranker=rr, top_m=20)

            # 知识库入库（首次）
            if store.count() == 0:
                pipe = IngestionPipeline(
                    embedding, store, contextual=False,
                    chunk_size=settings.rag.chunking.chunk_size,
                    chunk_overlap=settings.rag.chunking.chunk_overlap,
                )
                for f in sorted(Path("data/knowledge").glob("*.md")):
                    pipe.ingest_file(f)

            episodic = EpisodicMemory(
                Path(settings.memory.episodic.transcript_dir) / "u_001" / "m1.jsonl"
            )
            um = UserModelStore(settings.memory.user_model.path)
            tracer = TraceRecorder()

            self.embedding = embedding
            self.store = store
            self.llm = llm
            self.reranker = rr
            self.hybrid_search = hs
            self.episodic = episodic
            self.user_model = um
            self.tracer = tracer
            self._initialized = True

    # ── 会话级 JobCycle（LRU 缓存）──

    def _get_episodic(self, thread_id: str, user_id: str = "u_001"):
        """获取/创建 per-thread 情景记忆（每个对话一个 JSONL 文件）。"""
        key = f"{user_id}/{thread_id}"
        if key not in self._thread_episodics:
            from careercrew_core.memory.episodic import EpisodicMemory
            self._thread_episodics[key] = EpisodicMemory(
                Path(self.settings.memory.episodic.transcript_dir) / user_id / f"{thread_id}.jsonl"
            )
        return self._thread_episodics[key]

    def get_threads(self, user_id: str = "u_001") -> list[dict]:
        """列出用户的所有对话线程（按修改时间倒序）。"""
        self._ensure_heavy()
        import os
        transcript_dir = Path(self.settings.memory.episodic.transcript_dir) / user_id
        if not transcript_dir.exists():
            return []
        threads = []
        for f in sorted(transcript_dir.glob("*.jsonl"), key=os.path.getmtime, reverse=True):
            thread_id = f.stem
            title = thread_id
            try:
                lines = [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
                if not lines:
                    continue  # 跳过空线程（如运行时 touch 出来的 m1.jsonl）
                # 优先用 thread_title，其次 user_message
                for line in lines:
                    entry = json.loads(line)
                    if entry.get("type") == "thread_title":
                        title = str(entry.get("content", ""))[:50]
                        break
                    if entry.get("type") == "user_message":
                        title = str(entry.get("content", ""))[:50]
                        break
                else:
                    # 没有 user_message，取第一条有内容的条目
                    if lines:
                        entry = json.loads(lines[0])
                        content = entry.get("content", "")
                        if isinstance(content, dict):
                            title = str(content.get("q") or content.get("company") or content)[:50]
                        elif content:
                            title = str(content)[:50]
            except Exception:
                continue
            threads.append({"thread_id": thread_id, "title": title, "entries": len(lines)})
        return threads

    def get_cycle(self, thread_id: str, user_id: str = "u_001") -> "JobCycle":
        """按 thread_id 取/建 JobCycle（承接 match->resume 跨步骤历史与画像 preamble）。"""
        self._ensure_heavy()
        with self._cycles_lock:
            if thread_id in self._cycles:
                self._cycles.move_to_end(thread_id)
                return self._cycles[thread_id]
            from careercrew_cli.workflow.job_cycle import JobCycle

            ep = self._get_episodic(thread_id, user_id)
            jm = self.new_job_matcher(episodic=ep)
            ra = self.new_resume_advisor(episodic=ep)
            cycle = JobCycle(
                jm, ra, renderer=None, user_model_store=self.user_model,
                user_id=user_id, streaming=True,
            )
            self._cycles[thread_id] = cycle
            if len(self._cycles) > self._max_cycles:
                self._cycles.popitem(last=False)  # 逐出最旧
            return cycle

    def run_match_stream(self, thread_id: str, user_id: str, intent: str,
                         cb: Callable[[str], None] | None = None) -> str:
        """流式 match：用带 callback 的 agent 替换 cycle 中的 matcher，保留对话历史。"""
        cycle = self.get_cycle(thread_id, user_id)
        ep = self._get_episodic(thread_id, user_id)
        cycle.job_matcher = self.new_job_matcher(cb, episodic=ep)
        result = cycle.run_match(intent)
        # 存对话消息（user_message + agent_response）
        from careercrew_core.memory.types import MemoryEntry
        existing = ep._read_all()
        # 首条消息时生成对话标题
        if not existing:
            try:
                title_resp = self.llm.invoke(
                    f"用5-12个字概括这个求职需求的主题，只输出标题文字：{intent[:200]}"
                )
                title = (title_resp.content if isinstance(title_resp.content, str)
                         else str(title_resp.content)).strip().split("\n")[0][:20]
                ep.write(MemoryEntry(type="thread_title", content=title))
            except Exception:
                pass
        ep.write(MemoryEntry(type="user_message", content=intent))
        ep.write(MemoryEntry(type="agent_response", content=result))
        return result

    def run_resume_stream(self, thread_id: str, user_id: str, jd_text: str,
                          cb: Callable[[str], None] | None = None) -> str:
        """流式 resume：用带 callback 的 agent 替换 cycle 中的 advisor，保留对话历史。"""
        cycle = self.get_cycle(thread_id, user_id)
        ep = self._get_episodic(thread_id, user_id)
        cycle.resume_advisor = self.new_resume_advisor(cb, episodic=ep)
        result = cycle.run_resume(jd_text)
        from careercrew_core.memory.types import MemoryEntry
        ep.write(MemoryEntry(type="user_message", content=f"按这个 JD 定制简历：{jd_text[:200]}"))
        ep.write(MemoryEntry(type="agent_response", content=result))
        return result

    # ── agent 工厂（每次 new 一套，避免 last_result 并发串写）──

    def _make_tools(self, kind: str, episodic=None):
        """构造 agent 工具集。episodic 为 None 时用默认单例。"""
        from careercrew_core.tools.internal.memory_write import make_memory_write_tool
        from careercrew_core.tools.internal.profile_update import make_profile_update_tool
        from careercrew_core.tools.internal.rag_query import make_rag_query_tool
        from careercrew_core.tools.internal.search_jobs import search_jobs
        from careercrew_core.tools.registry import ToolRegistry, ToolSpec

        ep = episodic or self.episodic
        hs = self.hybrid_search
        tools = ToolRegistry()
        if kind == "matcher":
            tools.register(ToolSpec(tool=search_jobs))
            tools.register(ToolSpec(tool=make_rag_query_tool(hs)))
            tools.register(ToolSpec(tool=make_memory_write_tool(ep)))
            tools.register(ToolSpec(tool=make_profile_update_tool(self.user_model)))
        elif kind == "resume":
            tools.register(ToolSpec(tool=make_rag_query_tool(hs)))
            tools.register(ToolSpec(tool=make_profile_update_tool(self.user_model)))
        elif kind == "interviewer":
            tools.register(ToolSpec(tool=make_rag_query_tool(hs)))
            tools.register(ToolSpec(tool=make_memory_write_tool(ep)))
        elif kind == "salary" or kind == "planner":
            tools.register(ToolSpec(tool=make_rag_query_tool(hs)))
            tools.register(ToolSpec(tool=make_profile_update_tool(self.user_model)))
        return tools

    def new_job_matcher(self, cb: Callable[[str], None] | None = None, episodic=None):
        self._ensure_heavy()
        from careercrew_core.agents.job_matcher import JobMatcher

        return JobMatcher(
            llm=self.llm, tools=self._make_tools("matcher", episodic=episodic),
            max_iterations=8, tracer=self.tracer, stream_callback=cb,
        )

    def new_resume_advisor(self, cb: Callable[[str], None] | None = None, episodic=None):
        self._ensure_heavy()
        from careercrew_core.agents.resume_advisor import ResumeAdvisor

        return ResumeAdvisor(
            llm=self.llm, tools=self._make_tools("resume", episodic=episodic),
            max_iterations=8, tracer=self.tracer, stream_callback=cb,
        )

    def new_interviewer(self, cb: Callable[[str], None] | None = None, episodic=None):
        self._ensure_heavy()
        from careercrew_core.agents.interviewer import Interviewer

        return Interviewer(
            llm=self.llm, tools=self._make_tools("interviewer", episodic=episodic),
            max_iterations=8, tracer=self.tracer, stream_callback=cb,
        )

    def new_consult_agent(self, name: str, cb: Callable[[str], None] | None = None, episodic=None):
        """按名字建会诊 agent。"""
        self._ensure_heavy()
        if name == "salary_negotiator":
            from careercrew_core.agents.salary_negotiator import SalaryNegotiator

            return SalaryNegotiator(
                llm=self.llm, tools=self._make_tools("salary", episodic=episodic),
                max_iterations=8, tracer=self.tracer, stream_callback=cb,
            )
        if name == "career_planner":
            from careercrew_core.agents.career_planner import CareerPlanner

            return CareerPlanner(
                llm=self.llm, tools=self._make_tools("planner", episodic=episodic),
                max_iterations=8, tracer=self.tracer, stream_callback=cb,
            )
        raise ValueError(f"未知会诊 agent: {name}")

    # ── 直通方法 ──

    def score_answer(self, question: str, answer: str, max_score: int = 10) -> dict:
        self._ensure_heavy()
        from careercrew_core.agents.interviewer import score_answer

        return score_answer(question, answer, self.llm, max_score=max_score)

    def record_interview_qa(self, entries: list[dict]) -> int:
        self._ensure_heavy()
        from careercrew_core.agents.interviewer import record_interview_qa

        return record_interview_qa(self.episodic, entries)

    def read_image(self, path: str) -> str:
        """用视觉模型读图片内容。"""
        self._ensure_heavy()
        from careercrew_core.tools.internal.read_image import make_read_image_tool

        tool = make_read_image_tool(self.settings)
        return tool.invoke({"image_path": path, "prompt": "请描述图片内容并提取其中的文字。"})

    def load_document(self, path: str) -> str:
        """按扩展名路由加载文档为文本。"""
        from careercrew_core.rag.loaders.loader_factory import create_loader

        return create_loader(path).load(path).text

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
            agent = self.new_consult_agent(name)  # 每 agent 独立实例，无跨会话竞态
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
