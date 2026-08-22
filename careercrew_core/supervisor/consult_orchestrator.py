"""会诊总调度官：LangGraph 多轮 supervisor + 动态并行组。

总调度官（orchestrator）先分析用户问题，输出下一组要调用的顾问和每个顾问的
任务说明；图通过 ``Send`` 把这些顾问并行 fan-out，顾问完成后经 ``join`` 回到
orchestrator 继续决策，直到 ``next_agents`` 为空并给出最终答案。

保留 ``careercrew_core/supervisor/consult.py`` 的旧 fan-out 会诊和 ``_synthesize``；
本模块只新增自动调度路径，供 API 层使用。
"""
from __future__ import annotations

import json
import operator
from collections.abc import Callable
from typing import Annotated

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from careercrew_core.state.thread_state import CareerCrewState
from careercrew_core.supervisor.consult import _synthesize, opinion_fallback

AGENT_DESCRIPTIONS = {
    "salary_negotiator": "薪资谈判师：谈薪策略、薪资数据、offer 比较与话术。",
    "career_planner": "职业规划师：职业方向、阶段规划、能力画像与目标公司池。",
    "job_matcher": "职位匹配官：JD 匹配、目标岗位搜索与投递优先级。",
    "resume_advisor": "简历顾问：简历优化、JD 定制与面试准备材料。",
    "interviewer": "面试官：模拟面试、面经检索与答题质量评估。",
}

AGENT_LABELS = {
    "salary_negotiator": "薪资谈判师",
    "career_planner": "职业规划师",
    "job_matcher": "职位匹配官",
    "resume_advisor": "简历顾问",
    "interviewer": "面试官",
}


USER_INPUT_FIELDS: list[dict] = [
    {"id": "current_position", "label": "当前职位 / 行业", "placeholder": "例如：后端开发 / 互联网", "required": True},
    {"id": "experience_years", "label": "工作年限", "placeholder": "例如：3 年，中级", "required": True},
    {"id": "skills", "label": "核心技能", "placeholder": "例如：Python、RAG、大模型微调", "required": True},
    {"id": "target_direction", "label": "目标方向", "placeholder": "例如：大模型工程师、Agent 工程师", "required": True},
    {"id": "city", "label": "期望城市", "placeholder": "例如：上海、杭州", "required": False},
    {"id": "salary", "label": "期望薪资", "placeholder": "例如：目前 20k，期望 30-35k", "required": False},
    {"id": "target_companies", "label": "目标公司", "placeholder": "例如：字节、阿里（可填多个）", "required": False},
]

USER_INPUT_FIELD_IDS = [f["id"] for f in USER_INPUT_FIELDS]

USER_INPUT_FIELD_HINT = "、".join(
    f"{f['id']}（{f['label']}）" for f in USER_INPUT_FIELDS
)


class OrchestratorDecision(BaseModel):
    """总调度官单轮决策。

    ``next_agents`` 为空表示本轮直接给出最终答案；``tasks`` 是顾问名到任务说明
    的映射，缺失时由系统按默认任务补齐。

    ``needs_user_input`` 为 True 表示信息不足、需要用户补充基本资料才能继续；
    ``input_fields`` 是需要用户填写的字段 id（来自 ``USER_INPUT_FIELDS``）。
    """

    next_agents: list[str] = Field(default_factory=list)
    tasks: dict[str, str] = Field(default_factory=dict)
    final_answer: str = ""
    needs_user_input: bool = False
    input_fields: list[str] = Field(default_factory=list)


class ConsultOrchestratorState(CareerCrewState):
    """会诊编排状态：在通用求职状态上增加调度控制字段。"""

    orchestrator_round: int
    total_agent_calls: int
    next_agents: list[str]
    agent_tasks: dict[str, str]
    consult_calls: Annotated[list[dict], operator.add]
    pending_user_entry_id: str | None
    needs_user_input: bool
    input_fields: list[str]
    user_profile: str  # 用户已有画像摘要（能力画像/偏好），空串表示无


def _default_task(question: str, name: str) -> str:
    label = AGENT_LABELS.get(name, name)
    description = AGENT_DESCRIPTIONS.get(name, "")
    return f"你作为{label}，{description}\n请针对以下用户问题给出你的专业意见：\n{question}"


def _pick_default_agent(question: str) -> str:
    """按问题关键词路由默认顾问（首轮兜底调度用）。"""
    q = question or ""
    if any(k in q for k in ("薪资", "offer", "offer", "谈判", "薪水", "涨薪")):
        return "salary_negotiator"
    if any(k in q for k in ("匹配", "岗位", "投递", "职位", "jd", "JD")):
        return "job_matcher"
    if any(k in q for k in ("简历", "resume")):
        return "resume_advisor"
    if any(k in q for k in ("面试", "面经", "八股")):
        return "interviewer"
    return "career_planner"


def _decision_prompt(
    state: ConsultOrchestratorState,
    *,
    max_rounds: int,
    max_group_size: int,
    max_total_calls: int,
) -> str:
    question = state.get("user_intent", "")
    user_profile = state.get("user_profile", "") or ""
    current_round = state.get("orchestrator_round", 0) + 1
    used_calls = state.get("total_agent_calls", 0)
    previous_calls = state.get("consult_calls", [])

    agent_lines = "\n".join(
        f"- {name}（{AGENT_LABELS.get(name, name)}）：{AGENT_DESCRIPTIONS.get(name, '')}"
        for name in AGENT_DESCRIPTIONS
    )
    call_lines = []
    for call in previous_calls[-16:]:
        call_lines.append(
            f"第{call.get('round', 0)}轮 - {AGENT_LABELS.get(call.get('agent', ''), call.get('agent', ''))}"
            f"\n任务：{call.get('task', '')}\n结论：{call.get('content', '')}"
        )
    call_text = "\n\n".join(call_lines) if call_lines else "（尚无顾问执行记录）"

    force_finish = current_round > max_rounds or used_calls >= max_total_calls
    finish_instruction = (
        "本轮必须直接输出 final_answer，不得再调用任何顾问（已达轮次/调用上限）。"
        if force_finish
        else (
            "会诊的核心价值是调度顾问并行给出专业意见：只要不是需要用户补充资料，"
            "即使你认为信息足够，也应至少调度 1 个最相关的顾问获取专业意见后再综合；"
            "仅在确实没有合适顾问可调度时才直接输出 final_answer。"
        )
    )

    # 信息不足时请求用户补充基本资料（前端会弹出填写框，而不是让用户逐条打字）。
    # 只请求用户画像中缺失的字段，画像里已有的不再重复询问。
    input_instruction = (
        "如果结合「用户画像」仍缺少必要资料，需要用户补充缺失信息才能继续：\n"
        f"- 将 next_agents 设为空数组，needs_user_input 设为 true；\n"
        f"- 只从「用户画像中缺失」的字段中选择填入 input_fields（最多 {len(USER_INPUT_FIELDS)} 个）：{USER_INPUT_FIELD_HINT}；\n"
        "- final_answer 中简要说明需要补充什么（画像中已有的不要重复询问，不要替用户编造信息）。\n"
        "否则 needs_user_input 为 false，input_fields 为空数组。"
    )

    return f"""你是求职会诊的总调度官。你负责分析用户问题，选择最合适的顾问，并最终综合所有顾问结论给出答案。

用户问题：
{question}

用户画像（已有资料，来自能力画像 / 偏好；为空表示还没有）：
{user_profile or "（无，需要向用户收集）"}

可调度顾问：
{agent_lines}

当前是第 {current_round} 轮调度；已累计调用顾问 {used_calls} 次。
约束：
- 最多进行 {max_rounds} 轮调度。
- 每组最多 {max_group_size} 个顾问。
- 累计调用不超过 {max_total_calls} 次。
- 顾问可以多轮重复调用，但应优先选择最相关者。
- {finish_instruction}

已执行的顾问结论：
{call_text}

请只输出一个 JSON 对象，不要输出 Markdown 代码块或解释。格式：
{{"next_agents": ["顾问ID"], "tasks": {{"顾问ID": "该顾问本轮的具体任务"}}, "final_answer": "结束时的最终答案", "needs_user_input": false, "input_fields": []}}

关于 needs_user_input：
{input_instruction}

结束本轮时，next_agents 必须是空数组，final_answer 必须是完整、直接、中文的最终答案。
"""


def _parse_decision(text: str) -> OrchestratorDecision:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response does not contain JSON object")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("decision JSON is not an object")
    return OrchestratorDecision.model_validate(data)


def _decide_with_retry(llm: BaseChatModel, prompt: str) -> OrchestratorDecision:
    last_text = ""
    for attempt in range(2):
        resp = llm.invoke(prompt)
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        last_text = text
        try:
            return _parse_decision(text)
        except Exception:
            if attempt == 0:
                prompt = (
                    f"{prompt}\n\n上一次输出无法解析，请务必只输出一个合法 JSON 对象，"
                    "不要使用 Markdown 代码块，不要输出任何解释。"
                )
    raise ValueError(f"orchestrator decision parse failed: {last_text[:200]}")


def _build_orchestrator_node(
    llm: BaseChatModel,
    *,
    max_rounds: int,
    max_group_size: int,
    max_total_calls: int,
    emit: Callable[[dict], None] | None,
):
    def orchestrator_node(state: ConsultOrchestratorState) -> dict:
        current_round = state.get("orchestrator_round", 0) + 1
        used_calls = state.get("total_agent_calls", 0)
        prompt = _decision_prompt(
            state,
            max_rounds=max_rounds,
            max_group_size=max_group_size,
            max_total_calls=max_total_calls,
        )

        try:
            decision = _decide_with_retry(llm, prompt)
        except Exception:
            # 首轮解析失败退化为只问最通用的规划师；非首轮直接结束，由 API 层兜底综合。
            if current_round == 1:
                if emit:
                    emit({
                        "type": "dispatch",
                        "round": 1,
                        "agents": ["career_planner"],
                        "tasks": {
                            "career_planner": _default_task(state.get("user_intent", ""), "career_planner")
                        },
                    })
                return {
                    "orchestrator_round": 1,
                    "next_agents": ["career_planner"],
                    "agent_tasks": {
                        "career_planner": _default_task(state.get("user_intent", ""), "career_planner")
                    },
                    "needs_user_input": False,
                    "input_fields": [],
                }
            return {
                "orchestrator_round": current_round,
                "next_agents": [],
                "agent_tasks": {},
                "final_answer": "",
                "synthesis": "",
                "needs_user_input": False,
                "input_fields": [],
            }

        # 去重并过滤未知顾问，同时尊重组大小与总调用上限。
        seen: set[str] = set()
        agents: list[str] = []
        for name in decision.next_agents:
            if name in AGENT_DESCRIPTIONS and name not in seen:
                seen.add(name)
                agents.append(name)
        allowed = min(len(agents), max_group_size, max(0, max_total_calls - used_calls))
        agents = agents[:allowed]

        # 会诊兜底：还一个顾问都没调度过、又不需要用户补资料、也未达上限时，
        # 即使 LLM 想直接结束也强制调度一位最相关顾问，保证"会诊"确有顾问参与。
        force_finish = current_round > max_rounds or used_calls >= max_total_calls
        if (not agents or decision.final_answer.strip()) and used_calls == 0 \
                and not decision.needs_user_input and not force_finish:
            fallback = _pick_default_agent(state.get("user_intent", ""))
            fallback_task = _default_task(state.get("user_intent", ""), fallback)
            if emit:
                emit({
                    "type": "dispatch",
                    "round": current_round,
                    "agents": [fallback],
                    "tasks": {fallback: fallback_task},
                })
            return {
                "orchestrator_round": current_round,
                "next_agents": [fallback],
                "agent_tasks": {fallback: fallback_task},
                "needs_user_input": False,
                "input_fields": [],
            }

        if not agents or decision.final_answer.strip():
            final = decision.final_answer.strip()
            return {
                "orchestrator_round": current_round,
                "next_agents": [],
                "agent_tasks": {},
                "final_answer": final,
                "synthesis": final,
                "needs_user_input": bool(decision.needs_user_input),
                "input_fields": [
                    f for f in decision.input_fields if f in USER_INPUT_FIELD_IDS
                ][: len(USER_INPUT_FIELDS)],
            }

        tasks: dict[str, str] = {}
        for name in agents:
            tasks[name] = (decision.tasks or {}).get(name) or _default_task(
                state.get("user_intent", ""), name
            )
        if emit:
            emit({"type": "dispatch", "round": current_round, "agents": agents, "tasks": tasks})
        return {
            "orchestrator_round": current_round,
            "next_agents": agents,
            "agent_tasks": tasks,
            "needs_user_input": False,
            "input_fields": [],
        }

    return orchestrator_node


def _route_orchestrator(state: ConsultOrchestratorState):
    agents = state.get("next_agents") or []
    if not agents:
        return "end"
    return [Send(name, state) for name in agents]


def _build_agent_node(name: str, agent_factory: Callable, emit: Callable[[dict], None] | None):
    def agent_node(state: ConsultOrchestratorState) -> dict:
        round_no = state.get("orchestrator_round", 0)
        task = (state.get("agent_tasks") or {}).get(name) or _default_task(
            state.get("user_intent", ""), name
        )
        if emit:
            emit({"type": "agent_start", "agent": name, "round": round_no})

        def stream_cb(text: str):
            if emit:
                emit({"type": "chunk", "text": text, "agent": name, "round": round_no})

        agent = None
        try:
            agent = agent_factory(name, stream_cb)
            agent_state = {
                "thread_id": state.get("thread_id", ""),
                "user_id": state.get("user_id", ""),
                "stage": "consult",
                "user_intent": state.get("user_intent", ""),
                "messages": [HumanMessage(content=task)],
                "pending_action": None,
                "agent_outputs": {},
                "target_companies": [],
                "pending_user_entry_id": state.get("pending_user_entry_id"),
            }
            update = agent.run(agent_state) or {}
        except Exception:
            update = {
                "agent_outputs": {
                    name: {
                        "content": "",
                        "stopped_reason": "error",
                        "tool_calls_total": 0,
                        "iterations": 0,
                    }
                }
            }

        result = getattr(agent, "last_result", None)
        content = opinion_fallback(
            getattr(result, "content", ""), getattr(result, "stopped_reason", "")
        )
        if emit:
            emit({"type": "agent_end", "agent": name, "round": round_no})

        update["consult_calls"] = [
            {
                "round": round_no,
                "agent": name,
                "task": task,
                "content": content,
                # T3.5：被 HITL 拦截的调用随会诊结果透出，供路由落 awaiting_confirmation 行。
                "blocked_tool_calls": getattr(result, "blocked_tool_calls", None) or [],
            }
        ]
        return update

    return agent_node


def _join_node(state: ConsultOrchestratorState) -> dict:
    return {
        "total_agent_calls": state.get("total_agent_calls", 0)
        + len(state.get("next_agents") or [])
    }


def build_consult_orchestrator_graph(
    llm: BaseChatModel,
    agent_factory: Callable,
    *,
    max_rounds: int = 3,
    max_group_size: int = 3,
    max_total_calls: int = 8,
    emit: Callable[[dict], None] | None = None,
):
    """构建会诊总调度官 LangGraph。

    ``agent_factory(name, stream_callback)`` 返回一个具有 ``run(state)`` 与
    ``last_result`` 的顾问实例；每次调度都会新建实例，避免并发串写。
    """
    g = StateGraph(ConsultOrchestratorState)
    g.add_node(
        "orchestrator",
        _build_orchestrator_node(
            llm,
            max_rounds=max_rounds,
            max_group_size=max_group_size,
            max_total_calls=max_total_calls,
            emit=emit,
        ),
    )
    for name in AGENT_DESCRIPTIONS:
        g.add_node(name, _build_agent_node(name, agent_factory, emit))
    g.add_node("join", _join_node)

    g.add_edge(START, "orchestrator")
    path_map = {name: name for name in AGENT_DESCRIPTIONS}
    path_map["end"] = END
    g.add_conditional_edges("orchestrator", _route_orchestrator, path_map)
    for name in AGENT_DESCRIPTIONS:
        g.add_edge(name, "join")
    g.add_edge("join", "orchestrator")
    return g.compile()


def synthesize_fallback(
    opinions: dict[str, str], question: str, llm: BaseChatModel
) -> str:
    """决策失败或最终答案为空时的兜底综合。"""
    usable = {k: v for k, v in opinions.items() if v}
    if not usable:
        return "抱歉，本次会诊未能生成有效结论，请稍后重试。"
    return _synthesize(usable, question, llm)
