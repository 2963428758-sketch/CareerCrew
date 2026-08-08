"""职位匹配官 agent（E3/E4）。

第一个真实 agent：套 BaseAgent 的 ReAct 循环，工具 = search_jobs / rag_query / memory_write。
- E3：JD 检索 + 匹配打分（LLM 推理 + score_jd_match 确定性助手，可单测）
- E4：命中（≥0.6）由 agent 调 memory_write 写 job_match 事件到情景记忆
"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from careercrew_core.agents.base_agent import BaseAgent
from careercrew_core.tools.registry import ToolRegistry

_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "careercrew_ai" / "prompts" / "job_matcher.txt"
)

_DEFAULT_PROMPT = (
    "你是 CareerCrew 的职位匹配官。用 search_jobs 搜职位，评估匹配度，"
    "高匹配（≥0.6）用 memory_write(type=job_match) 入库，输出匹配岗位列表。"
)


def score_jd_match(jd_text: str, profile: dict) -> float:
    """确定性 JD-画像匹配打分（0-1）：技能关键词重合 + 方向命中。

    profile: {"skills": [...], "direction": "..."}
    用于单测验证打分逻辑；agent 推理时可用它做参考。
    """
    if not jd_text:
        return 0.0
    jd_lower = jd_text.lower()
    skills = [s for s in profile.get("skills", []) if s]
    total = len(skills) + (1 if profile.get("direction") else 0)
    if total == 0:
        return 0.0
    hit = sum(1 for s in skills if s.lower() in jd_lower)
    direction = (profile.get("direction") or "").lower()
    if direction and direction in jd_lower:
        hit += 1
    return round(hit / total, 3)


def extract_profile_from_intent(llm, intent: str) -> dict:
    """从用户最新消息提取【明确提供】的画像字段（direction/skills/level/city/target/salary）。

    只提取用户亲口说的，不推测、不从历史画像补充；解析失败返回空 dict（不阻塞）。
    返回 key 是 profile_update 白名单字段。用于匹配前刷新画像：用户本次说什么就是什么，
    避免 demo/历史画像（如旧 Java 技能）带偏方向。
    """
    if llm is None or not intent:
        return {}
    prompt = (
        "从用户这条求职需求里，提取用户【明确提供】的画像字段。"
        "只提取用户自己说的信息，不要推测，不要从历史画像补充；没提到的字段一律 null。\n"
        '输出 JSON：{"profile.direction": str 或 null, "profile.skills": [str] 或 null, '
        '"profile.level": str 或 null, "preferences.city": [str] 或 null, '
        '"target_companies": [str] 或 null, "preferences.salary_min": 数字 或 null}。'
        "只输出 JSON，不要解释。\n用户消息："
        f"{intent}"
    )
    try:
        resp = llm.invoke(prompt)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        data = json.loads(content[content.find("{") : content.rfind("}") + 1])
    except Exception:
        return {}
    fields: dict = {}
    for key, t in (
        ("profile.direction", str),
        ("profile.level", str),
        ("profile.skills", list),
        ("preferences.city", list),
        ("target_companies", list),
    ):
        v = data.get(key)
        if isinstance(v, t) and v:
            fields[key] = v
    sal = data.get("preferences.salary_min")
    if isinstance(sal, (int, float)) and not isinstance(sal, bool):
        fields["preferences.salary_min"] = int(sal)
    return fields


class JobMatcher(BaseAgent):
    """职位匹配官：搜 JD -> 匹配评估 -> 命中写情景记忆。"""

    def __init__(
        self,
        llm: BaseChatModel,
        tools: list[BaseTool] | ToolRegistry | None = None,
        max_iterations: int = 8,
        prompt_path: Path | None = None,
        tracer=None,
        stream_callback=None,
    ) -> None:
        path = prompt_path or _PROMPT_PATH
        prompt = path.read_text(encoding="utf-8") if path.exists() else _DEFAULT_PROMPT
        super().__init__(
            name="job_matcher",
            system_prompt=prompt,
            llm=llm,
            tools=tools,
            max_iterations=max_iterations,
            tracer=tracer,
            stream_callback=stream_callback,
        )
