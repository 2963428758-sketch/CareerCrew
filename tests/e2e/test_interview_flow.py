"""N5 场景 2：面试模拟全链路 出题 -> 问答 -> 评分 -> 写面经。

真实组件串联（LLM 用 FakeChatModel 预编排响应，不烧 token）：
Interviewer（BaseAgent + rag_query 工具检索面经）出题
-> score_answer（LLM 五维打分）
-> record_interview_qa（写入情景记忆树，append-only 链）
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.agents.interviewer import Interviewer, record_interview_qa, score_answer
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.tools.internal.rag_query import make_rag_query_tool
from careercrew_core.tools.registry import ToolRegistry, ToolSpec
from tests.fakes import FakeChatModel


class FakeHS:
    """知识库混合检索桩：返回预置的面经/八股片段。"""

    def __init__(self, snippets: list[str]) -> None:
        self._snippets = snippets

    def search(self, query, top_k=5, filters=None):
        from careercrew_ai.vector_store import QueryResult

        return [
            QueryResult(id=f"r{i}", score=0.9 - 0.05 * i, text=s, metadata={})
            for i, s in enumerate(self._snippets[:top_k])
        ]


def _state(text: str) -> dict:
    return {
        "thread_id": "t-interview", "user_id": "u1", "stage": "interview",
        "user_intent": "模拟大模型应用工程师面试",
        "messages": [HumanMessage(content=text)],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }


@pytest.mark.e2e
def test_interview_flow_generate_score_record() -> None:
    # 1) 出题：先 rag_query 检索面经，再基于结果出一组有梯度的问题
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=make_rag_query_tool(FakeHS([
        "RAG 八股：混合召回为什么要配 rerank？",
    ]))))
    interviewer = Interviewer(
        llm=FakeChatModel([
            AIMessage(content="", tool_calls=[
                {"name": "rag_query", "args": {"query": "大模型应用工程师 面经", "top_k": 3},
                 "id": "c1", "type": "tool_call"},
            ]),
            AIMessage(content="1. RAG 混合召回后为什么还要 rerank？\n2. ReAct 循环怎么终止？"),
        ]),
        tools=reg, max_iterations=5,
    )
    out = interviewer.run(_state("模拟大模型应用工程师面试"))
    produced = out["agent_outputs"]["interviewer"]
    assert "rerank" in produced["content"] and "ReAct" in produced["content"]
    assert produced["tool_calls_total"] == 1

    # 2) 候选作答 + LLM 评分
    score_llm = FakeChatModel([AIMessage(content="分数：9\n反馈：要点齐全，补充了成本权衡")])
    graded = score_answer("RAG 混合召回后为什么还要 rerank？", "先用 RRF 融合，再用交叉编码器精排……", score_llm)
    assert graded["score"] == 9.0 and "成本" in graded["feedback"]

    # 3) 写入情景记忆树（interview_qa，append-only 链）
    em = EpisodicMemory(FakeMemoryDb(), user_id="u1", thread_id="t-interview")
    record_interview_qa(em, [{
        "q": "RAG 混合召回后为什么还要 rerank？",
        "a": "先用 RRF 融合，再用交叉编码器精排……",
        "score": graded["score"],
    }])
    entries = em.list(type="interview_qa")
    assert len(entries) == 1
    assert entries[0].content["score"] == 9.0
