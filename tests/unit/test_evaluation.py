"""L1/L2 评估测试。"""
from __future__ import annotations

from careercrew_core.evaluation.answer_eval import CompositeEvaluator
from careercrew_core.evaluation.business_eval import BusinessEvaluator
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry


def test_composite_resume() -> None:
    ev = CompositeEvaluator()
    r = ev.evaluate_resume("Python LangChain RAG", "需要 Python LangChain RAG")
    assert r["metric"] == "resume_match"
    assert r["score"] == 1.0


def test_composite_interview_no_llm() -> None:
    r = CompositeEvaluator().evaluate_interview("q", "a")
    assert r["feedback"] == "未配置 LLM"


def test_composite_interview_with_llm() -> None:
    class FakeLLM:
        def invoke(self, prompt):
            from langchain_core.messages import AIMessage
            return AIMessage(content="分数：8\n反馈：不错")

    r = CompositeEvaluator(llm=FakeLLM()).evaluate_interview("讲讲 RAG", "检索增强")
    assert r["score"] == 8.0


def test_business_eval_stats(tmp_path) -> None:
    em = EpisodicMemory(tmp_path / "t.jsonl")
    em.write(MemoryEntry(type="application", content={"company": "A", "status": "submitted"}))
    em.write(MemoryEntry(type="application", content={"company": "B", "status": "submitted"}))
    em.write(MemoryEntry(type="interview_qa", content={"q": "q", "score": 8}))
    em.write(MemoryEntry(type="offer", content={"company": "A"}))
    s = BusinessEvaluator(em).stats()
    assert s["applications"] == 2
    assert s["interviews"] == 1
    assert s["offers"] == 1
    assert s["apply_to_interview_rate"] == 0.5
    assert s["interview_pass_rate"] == 1.0
