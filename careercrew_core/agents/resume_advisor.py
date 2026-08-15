"""简历顾问 agent（F）。

第二个真实 agent：套 BaseAgent 的 ReAct 循环，工具 = rag_query(简历范本) / profile_update。
- F2：rag_query 检索简历范本/写作要点（KB exa_resume.md）
- F3：按 JD 定制简历（LLM 生成）
- F4：resume_match_score 确定性打分（JD 技能在简历的覆盖率）+ LLM 参考
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from careercrew_core.agents.base_agent import BaseAgent
from careercrew_core.tools.registry import ToolRegistry

_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "careercrew_ai" / "prompts" / "resume_advisor.txt"
)

_DEFAULT_PROMPT = (
    "你是 CareerCrew 的简历顾问。用 rag_query 检索简历范本，按目标 JD 定制简历，"
    "评估匹配度（0-1）并输出改进建议。"
)


def prompt_source(prompt_path: Path | None = None) -> str:
    """返回本 agent 实际使用的 prompt 文本（与 __init__ 读取逻辑完全一致）。"""
    path = prompt_path or _PROMPT_PATH
    return path.read_text(encoding="utf-8") if path.exists() else _DEFAULT_PROMPT

# 简历-JD 匹配评估的常用技能词表
DEFAULT_SKILLS = [
    "python", "java", "go", "c++", "langchain", "langgraph", "rag", "agent",
    "pytorch", "tensorflow", "spring", "spring boot", "sql", "redis",
    "微调", "sft", "rlhf", "向量", "milvus", "chroma", "faiss", "mcp",
    "prompt", "docker", "kubernetes", "分布式", "多模态", "大模型",
]


def resume_match_score(resume_text: str, jd_text: str, skills: list[str] | None = None) -> float:
    """确定性简历-JD 匹配度（0-1）：JD 要求的技能在简历里的覆盖率。

    score = |JD 技能 ∩ 简历技能| / |JD 技能|。JD 无已知技能时返回 0.0。
    用于单测验证打分逻辑；L1 阶段集成 Ragas 做更完整的评估。
    """
    if not resume_text or not jd_text:
        return 0.0
    vocab = skills or DEFAULT_SKILLS
    resume_l = resume_text.lower()
    jd_l = jd_text.lower()
    jd_skills = [s for s in vocab if s in jd_l]
    if not jd_skills:
        return 0.0
    hit = sum(1 for s in jd_skills if s in resume_l)
    return round(hit / len(jd_skills), 3)


class ResumeAdvisor(BaseAgent):
    """简历顾问：rag_query 简历范本 -> 按 JD 定制 -> 匹配度评估。"""

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
            name="resume_advisor",
            system_prompt=prompt,
            llm=llm,
            tools=tools,
            max_iterations=max_iterations,
            stream_callback=stream_callback,
            memory_injector=memory_injector,
            history_loader=history_loader,
            compaction=compaction,
        )
