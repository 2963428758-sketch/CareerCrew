"""H 面试官测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.agents.interviewer import (
    Interviewer,
    _parse_score,
    record_interview_qa,
    score_answer,
)
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.tools.internal.rag_query import make_rag_query_tool
from careercrew_core.tools.registry import ToolRegistry, ToolSpec
from tests.fakes import FakeChatModel


def test_parse_score() -> None:
    out = _parse_score("分数：8\n反馈：答得不错，可补充细节", 10)
    assert out["score"] == 8.0
    assert "补充" in out["feedback"]


def test_parse_score_missing_returns_zero() -> None:
    assert _parse_score("回答不相关", 10)["score"] == 0.0


def test_score_answer_with_fake_llm() -> None:
    class FakeLLM:
        def invoke(self, prompt):
            return AIMessage(content="分数：9\n反馈：很完整")

    out = score_answer("讲讲 RAG", "检索增强生成...", FakeLLM())
    assert out["score"] == 9.0
    assert out["feedback"] == "很完整"


def test_interviewer_generates_questions_with_rag() -> None:
    class FakeHS:
        def search(self, query, top_k=5, filters=None):
            from careercrew_ai.vector_store import QueryResult
            return [QueryResult(id="r1", score=0.9, text="RAG 面试题：向量检索、rerank、幻觉处理", metadata={})]

    reg = ToolRegistry()
    reg.register(ToolSpec(tool=make_rag_query_tool(FakeHS())))
    agent = Interviewer(
        llm=FakeChatModel([
            AIMessage(content="", tool_calls=[
                {"name": "rag_query", "args": {"query": "大模型应用工程师 面试题", "top_k": 3}, "id": "c1", "type": "tool_call"}
            ]),
            AIMessage(content="1. RAG 怎么减少幻觉？\n2. 手写 ReAct 为什么？\n3. 如何设计多智能体？"),
        ]),
        tools=reg, max_iterations=5,
    )
    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "interview", "user_intent": "模拟大模型应用面试",
        "messages": [HumanMessage(content="模拟大模型应用工程师面试")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)
    assert "1." in agent.last_result.content
    assert agent.last_result.tool_calls_total == 1


def test_record_interview_qa() -> None:
    em = EpisodicMemory(FakeMemoryDb(), user_id="u1", thread_id="t1")
    n = record_interview_qa(em, [
        {"q": "RAG 怎么减幻觉", "a": "检索知识库", "score": 8},
        {"q": "什么是 Agent", "a": "能调工具", "score": 9},
    ])
    assert n == 2
    entries = em._read_all()
    assert all(e.type == "interview_qa" for e in entries)
    assert entries[1].parentId == entries[0].id  # append-only 链
