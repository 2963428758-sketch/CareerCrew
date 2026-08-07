"""Thread State 定义（B1）。

CareerCrewState 是 LangGraph supervisor 的 thread 级状态：当前求职阶段、用户意图、
短期对话（Context Window）、待确认动作（HITL）、各 agent 产出、目标公司池。

messages 用 add_messages reducer 累积（节点返回的新消息追加而非覆盖），
其余字段默认 last-write-wins。
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph import add_messages


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    """agent_outputs reducer：多 agent 产出按键合并（不互相覆盖）。"""
    out = dict(left or {})
    if right:
        out.update(right)
    return out

# 求职阶段（状态机的显式状态）
STAGES = (
    "intent",      # 意向
    "planning",    # 规划
    "match",       # 匹配
    "resume",      # 简历
    "interview",   # 面试
    "negotiate",   # 谈判
    "apply",       # 投递
    "track",       # 跟踪
    "review",      # 复盘
)


class CareerCrewState(TypedDict):
    """LangGraph thread 级状态（对齐 DEV_SPEC 3.1.3）。"""

    thread_id: str
    user_id: str
    stage: str  # STAGES 之一
    user_intent: str  # 用户当前意图
    messages: Annotated[list, add_messages]  # 短期对话 (Context Window)，累积
    pending_action: dict | None  # 待确认动作（HITL）
    agent_outputs: Annotated[dict, merge_dicts]  # 各 agent 产出（merge_dicts 聚合多 agent）
    target_companies: list[str]  # 目标公司池
