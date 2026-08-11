"""知识库问答 agent：基于多模态知识库检索回答用户问题。

独立于 supervisor 主流程，只服务"知识库问答"页面：
- rag_query 检索知识库（八股 / 面经 / JD / 简历范本 / 学习资料）
- 回答基于检索片段，注明依据来源
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from careercrew_core.agents.base_agent import BaseAgent
from careercrew_core.tools.registry import ToolRegistry

_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "careercrew_ai" / "prompts" / "knowledge_advisor.txt"
)

_DEFAULT_PROMPT = (
    "你是 CareerCrew 的知识库顾问。用 rag_query 检索知识库回答用户问题，"
    "并说明依据来源。"
)


class KnowledgeAdvisor(BaseAgent):
    """知识库顾问：rag_query 检索知识库 -> 基于检索结果回答。"""

    def __init__(
        self,
        llm: BaseChatModel,
        tools: list[BaseTool] | ToolRegistry | None = None,
        max_iterations: int = 15,
        prompt_path: Path | None = None,
        stream_callback=None,
    ) -> None:
        path = prompt_path or _PROMPT_PATH
        prompt = path.read_text(encoding="utf-8") if path.exists() else _DEFAULT_PROMPT
        super().__init__(
            name="knowledge_advisor",
            system_prompt=prompt,
            llm=llm,
            tools=tools,
            max_iterations=max_iterations,
            stream_callback=stream_callback,
        )
