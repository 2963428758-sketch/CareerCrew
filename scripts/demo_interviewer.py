"""阶段 H 可视化 demo：面试官出题 + 评分 + 写面经。"""
from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage

from careercrew_ai.embedding import create_embedding
from careercrew_ai.llm import create_llm
from careercrew_ai.reranker import create_reranker
from careercrew_ai.vector_store import create_vector_store
from careercrew_core.agents.interviewer import Interviewer, record_interview_qa, score_answer
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.rag.retrieval.hybrid_search import HybridSearch
from careercrew_core.state.settings import load_settings
from careercrew_core.tools.internal.memory_write import make_memory_write_tool
from careercrew_core.tools.internal.rag_query import make_rag_query_tool
from careercrew_core.tools.registry import ToolRegistry, ToolSpec


def main() -> None:
    settings = load_settings()
    print(f"LLM: {settings.llm.model}\n")
    embedding = create_embedding(settings)
    store = create_vector_store(settings)
    llm = create_llm(settings, max_tokens=1024)
    rr = create_reranker(settings)
    hs = HybridSearch(embedding, store, reranker=rr, top_m=20)
    episodic = EpisodicMemory(Path("data/transcripts/demo_user/interview.jsonl"))

    reg = ToolRegistry()
    reg.register(ToolSpec(tool=make_rag_query_tool(hs)))
    reg.register(ToolSpec(tool=make_memory_write_tool(episodic)))
    agent = Interviewer(llm=llm, tools=reg, max_iterations=8)

    topic = "模拟大模型应用工程师面试"
    print("=" * 64)
    print(f"面试官出题：{topic}")
    print("=" * 64)
    state = {
        "thread_id": "demo", "user_id": "demo_user", "stage": "interview", "user_intent": topic,
        "messages": [HumanMessage(content=topic)],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)
    for it in agent.last_result.iterations:
        for tc, tr in zip(it.tool_calls, it.tool_results):
            print(f"  → 调工具: {tc['name']}({tc['args']})")
    print("\n出题结果：")
    print(agent.last_result.content)

    # 评分演示（真实 LLM）
    print("\n" + "=" * 64)
    print("模拟问答评分：Q=RAG 怎么减少幻觉  A=通过检索真实知识库让生成有据可依，叠加 rerank")
    print("=" * 64)
    q = "RAG 怎么减少幻觉？"
    a = "通过检索真实知识库作为上下文，让生成有据可依，减少编造；叠加 rerank 提升相关性。"
    verdict = score_answer(q, a, llm)
    print(f"  分数: {verdict['score']}")
    print(f"  反馈: {verdict['feedback']}")

    # 写 interview_qa 到情景记忆
    n = record_interview_qa(episodic, [{"q": q, "a": a, "score": verdict["score"]}])
    print(f"\n已写 {n} 条 interview_qa 到情景记忆: {episodic.path}")


if __name__ == "__main__":
    main()
