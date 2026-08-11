"""运行时单例（§2）：重组件进程级单例 + 会话级 agent/JobCycle。

核心决策：
- 重组件（llm/embedding/store/reranker/MultimodalSearch/episodic/user_model）进程级单例
- agent 与 JobCycle 按会话(thread_id)新建（``BaseAgent.last_result`` 是可变属性，并发共享会串写）
- embedding.encode 加锁；user_model 写操作 per-user lock
- 初始化放首请求惰性触发（非 lifespan），uvicorn 秒起

组装逻辑与 ``careercrew_cli/app.py`` 的 ``_build_job_cycle`` 保持一致（去掉 Renderer 依赖）。
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

    from careercrew_cli.workflow.job_cycle import JobCycle


class RuntimeInitError(RuntimeError):
    """运行时初始化失败（重组件加载 / 向量库连接失败等），应映射为 503。"""


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
        self.multimodal_search = None
        self.ingest_pipeline = None
        self.episodic = None
        self.user_model = None

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
            from careercrew_core.memory.episodic import EpisodicMemory
            from careercrew_core.memory.user_model import UserModelStore
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

            # 知识库入库（首次：data/uploads 下的 PDF/图片/docx；data/knowledge 不参与）
            uploads_dir = Path(__file__).resolve().parents[1] / "data" / "uploads"
            if store.count() == 0:
                ingest_files = sorted(
                    p for p in uploads_dir.glob("*")
                    if p.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".docx"}
                )
                for f in ingest_files:
                    try:
                        pipe.ingest_file(f)
                    except Exception as e:
                        print(f"[runtime] ingest 跳过 {f}: {e}")

            episodic = EpisodicMemory(
                Path(settings.memory.episodic.transcript_dir) / "u_001" / "m1.jsonl"
            )
            um = UserModelStore(settings.memory.user_model.path)

            self.embedding = embedding
            self.store = store
            self.llm = llm
            self.reranker = rr
            self.multimodal_search = hs
            self.episodic = episodic
            self.user_model = um
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
        """列出用户的所有对话线程（按修改时间倒序）。

        只读文件系统，不需要初始化重栈（BGE-M3/Qdrant）。
        """
        from careercrew_core.state.settings import load_settings
        settings = self.settings or load_settings()
        base = Path(settings.memory.episodic.transcript_dir).resolve()
        transcript_dir = (base / user_id).resolve()
        if not transcript_dir.is_relative_to(base):
            return []  # 非法 user_id（路径穿越）直接视为无线程
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
        return traced_call(
            self._run_match_stream_impl,
            name="careercrew.match",
            run_type="chain",
            run_metadata={"endpoint": "match"},
            thread_id=thread_id,
            user_id=user_id,
            intent=intent,
            cb=cb,
        )

    def _run_match_stream_impl(self, thread_id: str, user_id: str, intent: str,
                               cb: Callable[[str], None] | None = None) -> str:
        attach_run_metadata(user_id=user_id, thread_id=thread_id, stage="match")
        cycle = self.get_cycle(thread_id, user_id)
        ep = self._get_episodic(thread_id, user_id)
        cycle.job_matcher = self.new_job_matcher(cb, episodic=ep)
        result = cycle.run_match(intent)
        # 超轮次兜底：agent 搜索轮次耗尽时补一段结论，避免以"我再搜一下"截断
        lr = getattr(cycle.job_matcher, "last_result", None)
        if lr is not None and getattr(lr, "stopped_reason", "") == "max_iterations":
            result = result + (
                "\n\n---\n*（搜索轮次已达上限，以上为已找到的匹配岗位。"
                "如需更精准结果，可补充城市/薪资/方向等条件后继续对话。）*"
            )
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
        return traced_call(
            self._run_resume_stream_impl,
            name="careercrew.resume",
            run_type="chain",
            run_metadata={"endpoint": "resume"},
            thread_id=thread_id,
            user_id=user_id,
            jd_text=jd_text,
            cb=cb,
        )

    def _run_resume_stream_impl(self, thread_id: str, user_id: str, jd_text: str,
                                cb: Callable[[str], None] | None = None) -> str:
        attach_run_metadata(user_id=user_id, thread_id=thread_id, stage="resume")
        cycle = self.get_cycle(thread_id, user_id)
        ep = self._get_episodic(thread_id, user_id)
        cycle.resume_advisor = self.new_resume_advisor(cb, episodic=ep)
        result = cycle.run_resume(jd_text)
        from careercrew_core.memory.types import MemoryEntry
        ep.write(MemoryEntry(type="user_message", content=f"按这个 JD 定制简历：{jd_text[:200]}"))
        ep.write(MemoryEntry(type="agent_response", content=result))
        return result

    def run_knowledge_ask_stream(self, question: str, user_id: str,
                                 cb: Callable[[str], None] | None = None) -> str:
        """知识库问答：KnowledgeAdvisor 基于 rag_query 检索流式回答（无状态）。

        返回 ``{"content": str, "sources": list[dict]}``：
        sources 为 agent 实际检索到的结构化片段（doc/source/score/text/image_path/page），
        供前端标注来源并点击查看原文。
        """
        return traced_call(
            self._run_knowledge_ask_stream_impl,
            name="careercrew.knowledge.ask",
            run_type="chain",
            run_metadata={"endpoint": "knowledge.ask"},
            question=question,
            user_id=user_id,
            cb=cb,
        )

    def _run_knowledge_ask_stream_impl(self, question: str, user_id: str,
                                       cb: Callable[[str], None] | None = None) -> str:
        attach_run_metadata(user_id=user_id, stage="knowledge")
        from langchain_core.messages import HumanMessage

        sources: list[dict] = []
        seen: set[str] = set()

        def _sink(r) -> None:
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
            })

        agent = self.new_knowledge_advisor(cb, rag_sink=_sink)
        state = {
            "thread_id": "knowledge", "user_id": user_id, "stage": "knowledge",
            "user_intent": question,
            "messages": [HumanMessage(content=question)],
            "pending_action": None, "agent_outputs": {}, "target_companies": [],
        }
        agent.run(state)
        content = (agent.last_result.content or "").strip()
        return {"content": content, "sources": sources}

    # ── agent 工厂（每次 new 一套，避免 last_result 并发串写）──

    def _make_tools(self, kind: str, episodic=None, rag_sink=None):
        """构造 agent 工具集。episodic 为 None 时用默认单例。"""
        from careercrew_core.tools.internal.memory_write import make_memory_write_tool
        from careercrew_core.tools.internal.profile_update import make_profile_update_tool
        from careercrew_core.tools.internal.rag_query import make_rag_query_tool
        from careercrew_core.tools.internal.search_jobs import search_jobs
        from careercrew_core.tools.registry import ToolRegistry, ToolSpec

        ep = episodic or self.episodic
        hs = self.multimodal_search
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
        elif kind == "knowledge":
            tools.register(ToolSpec(tool=make_rag_query_tool(hs, sink=rag_sink)))
        return tools

    def new_job_matcher(self, cb: Callable[[str], None] | None = None, episodic=None):
        self._ensure_heavy()
        from careercrew_core.agents.job_matcher import JobMatcher

        return JobMatcher(
            llm=self.llm, tools=self._make_tools("matcher", episodic=episodic),
            max_iterations=15, stream_callback=cb,
        )

    def new_resume_advisor(self, cb: Callable[[str], None] | None = None, episodic=None):
        self._ensure_heavy()
        from careercrew_core.agents.resume_advisor import ResumeAdvisor

        return ResumeAdvisor(
            llm=self.llm, tools=self._make_tools("resume", episodic=episodic),
            max_iterations=15, stream_callback=cb,
        )

    def new_interviewer(self, cb: Callable[[str], None] | None = None, episodic=None):
        self._ensure_heavy()
        from careercrew_core.agents.interviewer import Interviewer

        return Interviewer(
            llm=self.llm, tools=self._make_tools("interviewer", episodic=episodic),
            max_iterations=15, stream_callback=cb,
        )

    def new_knowledge_advisor(self, cb: Callable[[str], None] | None = None, episodic=None,
                              rag_sink=None):
        self._ensure_heavy()
        from careercrew_core.agents.knowledge_advisor import KnowledgeAdvisor

        return KnowledgeAdvisor(
            llm=self.llm, tools=self._make_tools("knowledge", episodic=episodic, rag_sink=rag_sink),
            max_iterations=15, stream_callback=cb,
        )

    def new_consult_agent(self, name: str, cb: Callable[[str], None] | None = None, episodic=None):
        """按名字建会诊 agent。"""
        self._ensure_heavy()
        if name == "salary_negotiator":
            from careercrew_core.agents.salary_negotiator import SalaryNegotiator

            return SalaryNegotiator(
                llm=self.llm, tools=self._make_tools("salary", episodic=episodic),
                max_iterations=15, stream_callback=cb,
            )
        if name == "career_planner":
            from careercrew_core.agents.career_planner import CareerPlanner

            return CareerPlanner(
                llm=self.llm, tools=self._make_tools("planner", episodic=episodic),
                max_iterations=15, stream_callback=cb,
            )
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
        """MinerU 解析为文本（resume 上传 pdf/docx 等；按 provider 走云端 API 或本地子进程）。"""
        loaders = self.settings.rag.loaders
        if loaders.provider == "local":
            from careercrew_core.rag.loaders.mineru_loader import MinerULoader

            parsed = MinerULoader(
                loaders.output_dir,
                device=loaders.device,
                method=loaders.method,
                formula=loaders.formula,
            ).parse(path)
        else:
            from careercrew_core.rag.loaders.mineru_api_loader import MinerUApiLoader

            parsed = MinerUApiLoader(
                loaders.output_dir,
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
        metadata: dict | None = None,
        progress_cb: Callable[[str, float], None] | None = None,
    ) -> dict:
        """知识库入库（多模态管线：md 走文本，PDF/图片走 MinerU）。

        progress_cb(stage, progress) 可选进度回调：stage ∈ parse/vectorize/store，
        progress ∈ [0, 1]（阶段边界处的真实进度，非秒级平滑值）。
        """
        self._ensure_heavy()
        from pathlib import Path

        p = Path(path)
        n = self.ingest_pipeline.ingest_file(p, metadata=metadata, progress_cb=progress_cb)
        return {"doc_id": p.stem, "points": n, "path": str(p)}

    def delete_document(self, doc_id: str) -> int:
        """按 doc_id 删除知识库文档的全部向量点。"""
        self._ensure_heavy()
        return self.store.delete_by_metadata({"doc": doc_id})

    def knowledge_status(self) -> dict:
        """知识库状态：总点数 + 文档列表。"""
        self._ensure_heavy()
        return {"points": self.store.count(), "docs": self.store.list_docs()}

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
