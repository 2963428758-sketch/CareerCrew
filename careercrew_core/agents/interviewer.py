"""面试官 agent（H）。

- H2：rag_query 检索面经/八股 出题（Interviewer agent）
- H3：score_answer LLM 评分
- H4：record_interview_qa 写 interview_qa 到情景记忆
"""
from __future__ import annotations

import re
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from careercrew_core.agents.base_agent import BaseAgent
from careercrew_core.tools.registry import ToolRegistry

_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "careercrew_ai" / "prompts" / "interviewer.txt"
)

_DEFAULT_PROMPT = (
    "你是 CareerCrew 的面试官。用 rag_query 检索面经/八股，出一组有梯度的面试题。"
)


class Interviewer(BaseAgent):
    """面试官：rag_query 面经/八股 -> 出一组有梯度的面试题。"""

    def __init__(
        self,
        llm: BaseChatModel,
        tools: list[BaseTool] | ToolRegistry | None = None,
        max_iterations: int = 8,
        prompt_path: Path | None = None,
        tracer=None,
    ) -> None:
        path = prompt_path or _PROMPT_PATH
        prompt = path.read_text(encoding="utf-8") if path.exists() else _DEFAULT_PROMPT
        super().__init__(
            name="interviewer",
            system_prompt=prompt,
            llm=llm,
            tools=tools,
            max_iterations=max_iterations,
            tracer=tracer,
        )


def score_answer(question: str, answer: str, llm: BaseChatModel, max_score: int = 10) -> dict:
    """LLM 评分（H3）：返回 {score: 0-max_score, feedback}。"""
    prompt = (
        f"你是面试官，给以下回答打分（0-{max_score}）并给简短反馈。\n\n"
        f"问题：{question}\n\n回答：{answer}\n\n"
        "输出格式：\n分数：X\n反馈：...（中文，1-2 句）"
    )
    resp = llm.invoke(prompt)
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    return _parse_score(content, max_score)


def _parse_score(content: str, max_score: int) -> dict:
    m = re.search(r"分数[：:]\s*(\d+(?:\.\d+)?)", content)
    score = float(m.group(1)) if m else 0.0
    score = max(0.0, min(float(max_score), score))
    m2 = re.search(r"反馈[：:]\s*(.+)", content, re.S)
    feedback = m2.group(1).strip() if m2 else content.strip()
    return {"score": round(score, 1), "feedback": feedback}


def record_interview_qa(episodic, entries: list[dict]) -> int:
    """写 interview_qa 到情景记忆（H4）。entries: [{q, a, score}, ...]"""
    from careercrew_core.tools.internal.memory_write import make_memory_write_tool

    tool = make_memory_write_tool(episodic)
    for e in entries:
        tool.invoke({"type": "interview_qa", "content": e})
    return len(entries)
