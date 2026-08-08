"""多 agent 会诊（M3）：fan-out + join。

同一问题（如"这个 offer 要不要接"）路由给多个 agent 并行给意见，LLM 综合。
提供简单 consult 函数 + LangGraph 并行 fan-out/join 图两种。
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from careercrew_core.agents.base_agent import BaseAgent
from careercrew_core.state.thread_state import CareerCrewState


def _synthesize(opinions: dict[str, str], question: str, llm: BaseChatModel) -> str:
    parts = "\n\n".join(f"【{name}】\n{content}" for name, content in opinions.items())
    prompt = (
        f"以下是多个求职顾问 agent 对问题 '{question}' 的意见，请综合成一份结论"
        "（共识 / 分歧 / 建议），中文。\n\n" + parts
    )
    resp = llm.invoke(prompt)
    return resp.content if isinstance(resp.content, str) else str(resp.content)


def consult(
    agents: dict[str, BaseAgent],
    question: str,
    llm: BaseChatModel,
    user_id: str = "u_001",
) -> dict:
    """多 agent 串行会诊（简单版）。返回 {opinions, synthesis}。"""
    opinions: dict[str, str] = {}
    for name, agent in agents.items():
        state = {
            "thread_id": "consult", "user_id": user_id, "stage": "review",
            "user_intent": question,
            "messages": [HumanMessage(content=question)],
            "pending_action": None, "agent_outputs": {}, "target_companies": [],
        }
        agent.run(state)
        opinions[name] = agent.last_result.content
    return {"opinions": opinions, "synthesis": _synthesize(opinions, question, llm)}


def build_consult_graph(agents: dict[str, BaseAgent], llm: BaseChatModel):
    """LangGraph 并行 fan-out + join 会诊图。

    START -> fan_out -> [agent...] (并行) -> join(综合) -> END
    """
    def fan_out(state: CareerCrewState) -> dict:
        return {}

    def join(state: CareerCrewState) -> dict:
        opinions = {
            name: out["content"]
            for name, out in (state.get("agent_outputs") or {}).items()
        }
        return {"synthesis": _synthesize(opinions, state.get("user_intent", ""), llm)}

    g = StateGraph(CareerCrewState)
    g.add_node("fan_out", fan_out)
    for name in agents:
        g.add_node(name, agents[name].run)
    g.add_node("join", join)
    g.add_edge(START, "fan_out")
    for name in agents:
        g.add_edge("fan_out", name)
        g.add_edge(name, "join")
    g.add_edge("join", END)
    return g.compile()
