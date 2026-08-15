"""B1 Thread State + checkpointer 测试。"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from careercrew_core.state.checkpointer import get_checkpointer, tenant_checkpoint_config
from careercrew_core.state.settings import Settings
from careercrew_core.state.thread_state import STAGES, CareerCrewState


def _content(m) -> str:
    """从 message（dict 或 BaseMessage）取 content。"""
    if isinstance(m, dict):
        return m.get("content", "")
    return getattr(m, "content", str(m))


def test_state_constructable() -> None:
    s: CareerCrewState = {
        "thread_id": "t1",
        "user_id": "u1",
        "stage": "intent",
        "user_intent": "找大模型应用岗位",
        "messages": [{"role": "user", "content": "hi"}],
        "pending_action": None,
        "agent_outputs": {},
        "target_companies": [],
    }
    assert s["stage"] in STAGES


def test_get_checkpointer_unknown_backend(valid_config_data: dict) -> None:
    valid_config_data["supervisor"]["checkpointer"]["backend"] = "redis"
    settings = Settings.model_validate(valid_config_data)
    with pytest.raises(NotImplementedError):
        get_checkpointer(settings)


def test_tenant_checkpointer_persists_state_across_invokes() -> None:
    """同一 thread_id 两次 invoke：checkpointer 应恢复上次状态 -> messages 累积 4 条。

    checkpointer 唯一后端为 Postgres（工厂行为由集成测试覆盖）；
    本用例用 langgraph 内存 saver 验证租户配置与持久化语义。
    """
    cp = MemorySaver()

    def echo_node(state: CareerCrewState) -> dict:
        return {"messages": [{"role": "assistant", "content": "step"}]}

    g = StateGraph(CareerCrewState)
    g.add_node("echo", echo_node)
    g.add_edge(START, "echo")
    g.add_edge("echo", END)
    app = g.compile(checkpointer=cp)

    cfg = tenant_checkpoint_config("u1", "t1")
    init = {
        "thread_id": "t1", "user_id": "u1", "stage": "intent", "user_intent": "",
        "messages": [{"role": "user", "content": "hi"}],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    app.invoke(init, config=cfg)
    r2 = app.invoke({"messages": [{"role": "user", "content": "again"}]}, config=cfg)
    # 无持久化则 r2 只有 [again, step]；持久化则 [hi, step, again, step]
    contents = [_content(m) for m in r2["messages"]]
    assert contents == ["hi", "step", "again", "step"]
