"""答案级评估（L1）：简历匹配度 / 面试题质量。

MVP 用确定性打分（resume_match_score）+ LLM 面试评分；L 后续可集成 Ragas
（pip install -e ".[eval]"）。
"""
from __future__ import annotations

from careercrew_core.agents.resume_advisor import resume_match_score


class CompositeEvaluator:
    """CompositeEvaluator：聚合多个答案级指标。"""

    def __init__(self, llm=None, skills: list[str] | None = None) -> None:
        self._llm = llm
        self._skills = skills

    def evaluate_resume(self, resume_text: str, jd_text: str) -> dict:
        score = resume_match_score(resume_text, jd_text, self._skills)
        return {"metric": "resume_match", "score": score, "max": 1.0}

    def evaluate_interview(self, question: str, answer: str) -> dict:
        if self._llm is None:
            return {"metric": "interview_quality", "score": 0.0, "max": 10, "feedback": "未配置 LLM"}
        from careercrew_core.agents.interviewer import score_answer

        r = score_answer(question, answer, self._llm)
        return {"metric": "interview_quality", "score": r["score"], "max": 10, "feedback": r["feedback"]}
