"""阶段 F 可视化 demo：简历顾问 agent 端到端。

跑法：conda run -n careercrew python scripts/demo_resume_advisor.py
展示：rag_query 简历范本 -> 按目标 JD 定制简历 -> 匹配度评估（真实 DeepSeek）
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage

from careercrew_ai.embedding import create_embedding
from careercrew_ai.llm import create_llm
from careercrew_ai.reranker import create_reranker
from careercrew_ai.vector_store import create_vector_store
from careercrew_core.agents.resume_advisor import ResumeAdvisor, resume_match_score
from careercrew_core.memory.user_model import UserModelStore
from careercrew_core.rag.pipeline import IngestionPipeline
from careercrew_core.rag.retrieval.hybrid_search import HybridSearch
from careercrew_core.state.settings import load_settings
from careercrew_core.tools.internal.profile_update import make_profile_update_tool
from careercrew_core.tools.internal.rag_query import make_rag_query_tool
from careercrew_core.tools.registry import ToolRegistry, ToolSpec


def ensure_kb(embedding, store, settings) -> None:
    if store.count() > 0:
        print(f"知识库已入库（{store.count()} chunks）")
        return
    print("ingest 知识库（首次）...")
    pipe = IngestionPipeline(embedding, store, contextual=False, chunk_size=settings.rag.chunking.chunk_size, chunk_overlap=settings.rag.chunking.chunk_overlap)
    total = sum(pipe.ingest_file(f) for f in sorted(Path("data/knowledge").glob("*.md")))
    print(f"ingest 完成: {total} chunks\n")


def main() -> None:
    settings = load_settings()
    print(f"LLM: {settings.llm.model}")
    embedding = create_embedding(settings)
    store = create_vector_store(settings)
    ensure_kb(embedding, store, settings)

    llm = create_llm(settings, max_tokens=2000)
    reranker = create_reranker(settings)
    hs = HybridSearch(embedding, store, reranker=reranker, top_m=20)
    um = UserModelStore(Path("data/demo_c/user_model.json"))
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=make_rag_query_tool(hs)))
    reg.register(ToolSpec(tool=make_profile_update_tool(um, user_id="demo_user")))

    agent = ResumeAdvisor(llm=llm, tools=reg, max_iterations=8)

    jd = "字节跳动 大模型应用工程师：Agent 应用开发，RAG 系统，LangChain/LangGraph，Python，向量检索，30-50K，北京"
    query = (
        f"帮我按这个 JD 定制简历：{jd}\n"
        "我的背景：Python / LangChain / LangGraph / RAG / Agent 3 年经验，"
        "做过 Agent 应用和 RAG 检索系统（QPS 500+），有 Java 后端背景。"
    )
    print(f"\n用户: {query[:120]}...")
    state = {
        "thread_id": "demo", "user_id": "demo_user", "stage": "resume", "user_intent": query,
        "messages": [HumanMessage(content=query)],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)

    for it in agent.last_result.iterations:
        print(f"\n--- 轮次 {it.iteration + 1} ---")
        if it.content:
            print(f"  思考: {it.content[:200]}")
        for tc, tr in zip(it.tool_calls, it.tool_results):
            print(f"  调工具: {tc['name']}({tc['args']})")
            print(f"  返回: {str(tr)[:150]}")
        if not it.tool_calls:
            print("  (无工具调用 -> 最终答案)")

    print("\n" + "=" * 64)
    print("最终答案（定制简历）:")
    print(agent.last_result.content)
    print("=" * 64)
    r = agent.last_result
    print(f"统计: {len(r.iterations)} 轮, {r.tool_calls_total} 次工具调用, 停止={r.stopped_reason}")


if __name__ == "__main__":
    main()
