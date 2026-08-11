"""LangGraph supervisor 图（B3）。

supervisor 节点 -> 条件路由(route) -> agent 节点 -> 回 supervisor -> ... -> END。
checkpointer 持久化 thread 状态（B1）。agent 在执行中可改 stage 推进流程或终止。

分工必然性：LangGraph 擅长状态机/路由/中断/持久化，agent 节点内 create_agent 管工具推理。
"""
from __future__ import annotations

from typing import Callable

from langgraph.graph import END, START, StateGraph

from careercrew_core.state.thread_state import CareerCrewState
from careercrew_core.supervisor.router import route


def build_graph(agents: dict[str, Callable], checkpointer=None):
    """构建 supervisor 图。

    Args:
        agents: name -> 节点 callable（BaseAgent.run 或任意 (state)->dict）。
                必须覆盖 route 可能返回的所有 agent 名，否则条件路由落空。
        checkpointer: thread 级状态持久化（B1 的 get_checkpointer）。

    Returns:
        CompiledGraph。
    """
    g = StateGraph(CareerCrewState)

    def supervisor_node(state: CareerCrewState) -> dict:
        """supervisor 不直接改 state，只做路由（route 在 conditional_edges 调）。"""
        return {}

    g.add_node("supervisor", supervisor_node)
    for name, fn in agents.items():
        g.add_node(name, fn)

    g.add_edge(START, "supervisor")

    # supervisor 条件路由：route 返回 agent 名或 __end__
    path_map = {name: name for name in agents}
    path_map["__end__"] = END
    g.add_conditional_edges("supervisor", route, path_map)

    # 每个 agent 执行完回到 supervisor
    for name in agents:
        g.add_edge(name, "supervisor")

    return g.compile(checkpointer=checkpointer)
