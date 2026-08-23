"""长期记忆候选的确定性高精度入口。

这里故意宁缺毋滥：只有明确、可结构化且跨会话有价值的用户自述才成为候选。
LLM 判断可在此之后扩展，但不得绕过这些负规则。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_GENERIC_PATTERNS = (
    re.compile(r"(?:是什么|怎么用|如何|教程|原理|天气|新闻|价格|股价|翻译)"),
    re.compile(r"(?:忽略.*指令|system prompt|提示词|密码|token|密钥)", re.I),
)
_EXPERIENCE = re.compile(r"我有\s*(\d{1,2})\s*年\s*([^，。；;]{1,40}?)(?:经验|工作经验)")
_DIRECTION = re.compile(r"(?:想转|转向|目标岗位(?:是|为)|想做)\s*([^，。；;]{2,40})")
_WORK_MODE = re.compile(r"(?:只考虑|希望|偏好)\s*(远程|remote|现场|混合)\s*(?:工作|岗位|办公)?", re.I)


@dataclass(frozen=True)
class MemoryCandidate:
    field: str
    value: object
    reason: str


def extract_candidates(text: str, *, explicit: bool = False) -> list[MemoryCandidate]:
    """抽取稳定职业事实；普通问答与临时请求严格返回空列表。"""
    normalized = " ".join((text or "").strip().split())
    if not normalized or any(pattern.search(normalized) for pattern in _GENERIC_PATTERNS):
        return []
    candidates: list[MemoryCandidate] = []
    if match := _EXPERIENCE.search(normalized):
        candidates.append(MemoryCandidate(
            "profile.experience_years", int(match.group(1)), f"明确陈述 {match.group(1)} 年经验",
        ))
    if match := _WORK_MODE.search(normalized):
        mode = match.group(1).casefold()
        candidates.append(MemoryCandidate(
            "preferences.work_mode", {"remote": "远程"}.get(mode, mode), "明确工作方式偏好",
        ))
    if match := _DIRECTION.search(normalized):
        direction = match.group(1).strip(" ，。；;")
        if len(direction) >= 2:
            candidates.append(MemoryCandidate("profile.direction", direction, "明确职业方向变更"))
    # “记住”不会把任意自由文本变成事实；它只放宽已知结构化字段的门槛。
    return candidates
