"""薪资谈判师 agent（J1/J2）。"""
from __future__ import annotations

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from careercrew_core.agents.base_agent import BaseAgent
from careercrew_core.tools.registry import ToolRegistry

_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "careercrew_ai" / "prompts" / "salary_negotiator.txt"
)

_DEFAULT_PROMPT = (
    "你是 CareerCrew 的薪资谈判师。用 salary_query/rag_query/memory_search "
    "查薪资数据，制定谈薪策略与话术。"
)


class SalaryNegotiator(BaseAgent):
    """薪资谈判师：rag_query 薪资数据 -> 谈薪策略 + 话术。"""

    def __init__(
        self,
        llm: BaseChatModel,
        tools: list[BaseTool] | ToolRegistry | None = None,
        max_iterations: int = 8,
        prompt_path: Path | None = None,
        stream_callback=None,
        memory_injector=None,
        history_loader=None,
        compaction=None,
    ) -> None:
        path = prompt_path or _PROMPT_PATH
        prompt = path.read_text(encoding="utf-8") if path.exists() else _DEFAULT_PROMPT
        super().__init__(
            name="salary_negotiator",
            system_prompt=prompt,
            llm=llm,
            tools=tools,
            max_iterations=max_iterations,
            stream_callback=stream_callback,
            memory_injector=memory_injector,
            history_loader=history_loader,
            compaction=compaction,
        )
