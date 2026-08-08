"""CareerCrew CLI 入口。config 校验 + chat 求职对话（G 阶段 M1 闭环）。"""
from __future__ import annotations

import argparse
import sys

__version__ = "0.1.0"

BANNER = (
    "CareerCrew v{v} - 多智能体职业顾问团队\n"
    "职位匹配 / 简历 / 面试 / 谈薪 / 规划"
).format(v=__version__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="careercrew", description="CareerCrew 求职顾问 CLI")
    parser.add_argument("--version", action="version", version=f"careercrew {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("chat", help="启动求职顾问对话（M1 闭环：匹配->简历）")
    sub.add_parser("config", help="加载并校验配置（fail-fast）")
    return parser


def _run_config_check() -> int:
    from careercrew_core.state.settings import load_settings

    try:
        settings = load_settings()
    except Exception as e:
        print(f"[配置校验失败] {e}", file=sys.stderr)
        return 1
    print("[配置校验通过]")
    print(f"  LLM        : {settings.llm.model} @ {settings.llm.base_url}")
    print(f"  Embedding  : {settings.embedding.provider} ({settings.embedding.model})")
    print(f"  Rerank     : {settings.rerank.backend}")
    print(f"  VectorStore: {settings.vector_store.backend}")
    print(f"  RAG        : {settings.rag.retrieval.mode} / contextual={settings.rag.chunking.contextual}")
    return 0


def _build_job_cycle():
    """构建 M1 闭环（真实 agent + 工具 + 记忆 + RAG）。"""
    from pathlib import Path

    from careercrew_ai.embedding import create_embedding
    from careercrew_ai.llm import create_llm
    from careercrew_ai.reranker import create_reranker
    from careercrew_ai.vector_store import create_vector_store
    from careercrew_cli.workflow.job_cycle import JobCycle
    from careercrew_core.agents.job_matcher import JobMatcher
    from careercrew_core.agents.resume_advisor import ResumeAdvisor
    from careercrew_core.memory.episodic import EpisodicMemory
    from careercrew_core.memory.user_model import UserModelStore
    from careercrew_core.rag.pipeline import IngestionPipeline
    from careercrew_core.rag.retrieval.hybrid_search import HybridSearch
    from careercrew_core.state.settings import load_settings
    from careercrew_core.tools.internal.memory_write import make_memory_write_tool
    from careercrew_core.tools.internal.profile_update import make_profile_update_tool
    from careercrew_core.tools.internal.rag_query import make_rag_query_tool
    from careercrew_core.tools.internal.search_jobs import search_jobs
    from careercrew_core.tools.registry import ToolRegistry, ToolSpec
    from careercrew_core.tracing.trace import TraceRecorder
    from careercrew_ui.cli.renderer import Renderer

    settings = load_settings()
    embedding = create_embedding(settings)
    store = create_vector_store(settings)
    llm = create_llm(settings, max_tokens=1024)
    rr = create_reranker(settings)
    hs = HybridSearch(embedding, store, reranker=rr, top_m=20)

    # 确保知识库已入库
    if store.count() == 0:
        pipe = IngestionPipeline(
            embedding, store, contextual=False,
            chunk_size=settings.rag.chunking.chunk_size,
            chunk_overlap=settings.rag.chunking.chunk_overlap,
        )
        for f in sorted(Path("data/knowledge").glob("*.md")):
            pipe.ingest_file(f)
        print("[chat] 知识库已入库")

    episodic = EpisodicMemory(Path(settings.memory.episodic.transcript_dir) / "u_001" / "m1.jsonl")
    um = UserModelStore(settings.memory.user_model.path)

    matcher_tools = ToolRegistry()
    matcher_tools.register(ToolSpec(tool=search_jobs))
    matcher_tools.register(ToolSpec(tool=make_rag_query_tool(hs)))
    matcher_tools.register(ToolSpec(tool=make_memory_write_tool(episodic)))
    matcher_tools.register(ToolSpec(tool=make_profile_update_tool(um)))  # 持久化用户画像, 避免重复问

    resume_tools = ToolRegistry()
    resume_tools.register(ToolSpec(tool=make_rag_query_tool(hs)))
    resume_tools.register(ToolSpec(tool=make_profile_update_tool(um)))

    tracer = TraceRecorder()  # L3 全链路 trace（Dashboard 追踪页）
    renderer = Renderer()
    return JobCycle(
        JobMatcher(llm=llm, tools=matcher_tools, max_iterations=8, tracer=tracer,
                   stream_callback=renderer.stream),  # 流式输出, 用户不等
        ResumeAdvisor(llm=llm, tools=resume_tools, max_iterations=8, tracer=tracer,
                      stream_callback=renderer.stream),
        renderer=renderer,
        user_model_store=um,
    )


def _run_chat() -> int:
    from careercrew_ui.cli.renderer import Renderer

    renderer = Renderer()
    renderer.banner()
    print("\n[chat] M1 求职闭环：输入求职需求 -> 匹配官找岗位 -> 选 JD -> 简历顾问定制简历")
    print('  例："我是大模型应用方向，有 Java 背景，帮我找工作并定制简历"')
    print('  输入 "退出" 结束。\n')
    try:
        cycle = _build_job_cycle()
    except Exception as e:
        renderer.show_error(f"初始化失败: {e}")
        return 1

    while True:
        try:
            line = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            return 0
        if not line or line.lower() in ("退出", "quit", "exit", "q"):
            print("再见")
            return 0
        try:
            cycle.run(line)
        except Exception as e:
            renderer.show_error(f"处理失败: {e}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "config":
        return _run_config_check()
    if args.command == "chat":
        return _run_chat()
    print(BANNER)
    if args.command is None:
        print("\n用法：careercrew config | careercrew chat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
