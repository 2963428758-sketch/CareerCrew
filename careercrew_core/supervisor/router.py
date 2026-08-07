"""supervisor 路由（B3）。

按求职阶段 stage -> agent 名（或 __end__）。状态机路由可解释、可测试。
apply 阶段路由到 __end__（HITL 闸门，K 阶段接 LangGraph interrupt 暂停）。
"""
from __future__ import annotations

# stage -> agent 名（或 __end__）
STAGE_AGENT_MAP: dict[str, str] = {
    "intent": "career_planner",       # 意向 -> 规划师建画像
    "planning": "career_planner",     # 规划
    "match": "job_matcher",           # 匹配官搜 JD
    "resume": "resume_advisor",       # 简历顾问
    "interview": "interviewer",       # 面试官
    "negotiate": "salary_negotiator", # 谈判师
    "apply": "__end__",               # HITL 闸门（K 阶段）
    "track": "job_matcher",           # 跟踪（匹配官兼）
    "review": "career_planner",       # 复盘（规划师兼）
}

# 5 个 agent 名（supervisor 可路由的目标）
AGENT_NAMES = ("job_matcher", "resume_advisor", "interviewer", "salary_negotiator", "career_planner")


def route(state: dict) -> str:
    """stage -> agent 名（或 __end__）。未知 stage -> __end__。"""
    stage = state.get("stage", "intent")
    return STAGE_AGENT_MAP.get(stage, "__end__")
