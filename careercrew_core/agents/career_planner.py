"""职业规划师 agent（J3）。"""
from __future__ import annotations

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from careercrew_core.agents.base_agent import BaseAgent
from careercrew_core.tools.registry import ToolRegistry

_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "careercrew_ai" / "prompts" / "career_planner.txt"
)

_DEFAULT_PROMPT = (
    "你是 CareerCrew 的职业规划师。用 profile_update 建画像和目标公司池，制定阶段规划。"
)


class CareerPlanner(BaseAgent):
    """职业规划师：建能力画像 + 目标公司池（梯队）+ 阶段规划。"""

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
            name="career_planner",
            system_prompt=prompt,
            llm=llm,
            tools=tools,
            max_iterations=max_iterations,
            stream_callback=stream_callback,
            memory_injector=memory_injector,
            history_loader=history_loader,
            compaction=compaction,
        )
