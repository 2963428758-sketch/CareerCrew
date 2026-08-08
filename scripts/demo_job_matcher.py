"""阶段 E 可视化 demo：职位匹配官 agent 端到端。

跑法：conda run -n careercrew python scripts/demo_job_matcher.py
展示：
  1) 知识库入库（已入库则跳过，Milvus count() 判断）
  2) JobMatcher agent（真实 DeepSeek）跑 ReAct：search_jobs 搜 JD + rag_query 查 KB + 匹配评估
  3) 命中岗位调 memory_write 写 job_match 到情景记忆
  4) 逐轮打印 trace + 最终答案 + 记忆文件中的 job_match 事件
"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import HumanMessage

from careercrew_ai.embedding import create_embedding
from careercrew_ai.llm import create_llm
from careercrew_ai.reranker import create_reranker
from careercrew_ai.vector_store import create_vector_store
from careercrew_core.agents.job_matcher import JobMatcher
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.rag.pipeline import IngestionPipeline
from careercrew_core.rag.retrieval.hybrid_search import HybridSearch
from careercrew_core.state.settings import load_settings
from careercrew_core.tools.internal.memory_write import make_memory_write_tool
from careercrew_core.tools.internal.rag_query import make_rag_query_tool
from careercrew_core.tools.internal.search_jobs import search_jobs
from careercrew_core.tools.registry import ToolRegistry, ToolSpec


def ensure_kb(embedding, store, settings) -> None:
    if store.count() > 0:
        print(f"知识库已入库（{store.count()} chunks），跳过 ingest")
        return
    print("ingest 知识库（首次，约 3-4 分钟）...")
    pipe = IngestionPipeline(
        embedding, store, contextual=False,
        chunk_size=settings.rag.chunking.chunk_size, chunk_overlap=settings.rag.chunking.chunk_overlap,
    )
    total = 0
    for f in sorted(Path("data/knowledge").glob("*.md")):
        n = pipe.ingest_file(f)
        print(f"  {f.name}: {n} chunks")
        total += n
    print(f"ingest 完成: {total} chunks\n")


def main() -> None:
    settings = load_settings()
    print(f"LLM: {settings.llm.model}")
    embedding = create_embedding(settings)
    store = create_vector_store(settings)
    ensure_kb(embedding, store, settings)

    # 组装 JobMatcher 工具：search_jobs + rag_query + memory_write
    llm = create_llm(settings, max_tokens=1024)
    reranker = create_reranker(settings)
    hs = HybridSearch(embedding, store, reranker=reranker, top_m=20)
    episodic = EpisodicMemory(Path("data/transcripts/demo_user/demo_thread.jsonl"))
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=search_jobs))
    reg.register(ToolSpec(tool=make_rag_query_tool(hs)))
    reg.register(ToolSpec(tool=make_memory_write_tool(episodic)))

    agent = JobMatcher(llm=llm, tools=reg, max_iterations=10)

    query = "我是大模型应用/Agent 方向，擅长 Python、LangChain、LangGraph、RAG，有 Java 后端背景，目标 30-45K，帮我找匹配岗位"
    print(f"\n用户: {query}")
    state = {
        "thread_id": "demo", "user_id": "demo_user", "stage": "match", "user_intent": query,
        "messages": [HumanMessage(content=query)],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)

    # 逐轮打印 ReAct trace
    for it in agent.last_result.iterations:
        print(f"\n--- 轮次 {it.iteration + 1} ---")
        if it.content:
            print(f"  思考: {it.content[:200]}")
        for tc, tr in zip(it.tool_calls, it.tool_results):
            print(f"  调工具: {tc['name']}({tc['args']})")
            print(f"  返回: {str(tr)[:160]}")
        if not it.tool_calls:
            print("  (无工具调用 -> 最终答案)")

    print("\n" + "=" * 64)
    print("最终答案:")
    print(agent.last_result.content)
    print("=" * 64)
    r = agent.last_result
    print(f"统计: {len(r.iterations)} 轮, {r.tool_calls_total} 次工具调用, 停止={r.stopped_reason}")

    # 展示写入记忆的 job_match 事件
    print("\n=== 情景记忆中的 job_match 事件 ===")
    entries = [json.loads(l) for l in episodic.path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for e in entries:
        if e["type"] == "job_match":
            print(f"  {e['id']} {e['type']}: {e['content']}")


if __name__ == "__main__":
    main()
