"""T3.5 HITL 拦截中间件测试（block-and-record，无 approve/reject 恢复）。"""
from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from careercrew_ai.agents.langchain_agent import (
    HitlMiddleware,
    build_agent,
    run_agent,
)
from tests.fakes import FakeChatModel


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool
def submit_application(company: str) -> str:
    """Submit job application (high risk)."""
    return f"applied to {company}"


def _tc(name: str, args: dict, id_: str = "c1") -> dict:
    return {"name": name, "args": args, "id": id_, "type": "tool_call"}


def test_hitl_middleware_blocks_execution_and_feeds_toolmessage() -> None:
    """requires_hitl 工具在 wrap_tool_call 不执行 handler，回喂 ToolMessage。"""
    executed: list[str] = []
    mw = HitlMiddleware(requires_hitl={"submit_application"})

    req = type("R", (), {"tool_call": _tc("submit_application", {"company": "字节"})})()

    def handler(r):
        executed.append(r.tool_call["name"])
        return "EXECUTED"

    out = mw.wrap_tool_call(req, handler)
    assert executed == []  # 未执行
    assert "需要用户确认" in out.content
    assert out.tool_call_id == "c1"
    assert out.name == "submit_application"
    # 被拦截明细已记录
    assert mw.blocked_tool_calls == [
        {"name": "submit_application", "args": {"company": "字节"}},
    ]


def test_hitl_middleware_passes_non_hitl_through() -> None:
    mw = HitlMiddleware(requires_hitl={"submit_application"})
    req = type("R", (), {"tool_call": _tc("add", {"a": 1, "b": 2})})()

    def handler(r):
        return 3

    assert mw.wrap_tool_call(req, handler) == 3
    assert mw.blocked_tool_calls == []


def test_run_agent_surfaces_blocked_tool_calls() -> None:
    """真跑 create_agent：HITL 工具被拦截，blocked_tool_calls 记录且工具未执行副作用。"""
    called: list[str] = []
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("submit_application", {"company": "字节"})]),
        AIMessage(content="无法投递：需要你确认"),
    ])
    agent = build_agent(
        llm=llm, tools=[submit_application], system_prompt="sys",
        max_iterations=5, hitl_requires={"submit_application"},
    )
    result = run_agent(agent, [HumanMessage(content="投递字节")])
    assert result.blocked_tool_calls == [
        {"name": "submit_application", "args": {"company": "字节"}},
    ]
    assert result.content == "无法投递：需要你确认"


def test_observability_maps_blocked_to_awaiting_confirmation() -> None:
    """T3.5：blocked_tool_calls 被翻译成 tool_call 行
    status=awaiting_confirmation + hitl_status=pending + requires_hitl（落库诊断）。"""
    from careercrew_api.runtime import _observability_from_result

    result = type("R", (), {
        "input_tokens": 10, "output_tokens": 5,
        "tool_call_details": [],
        "blocked_tool_calls": [
            {"name": "submit_application", "args": {"company": "字节"}},
        ],
    })()
    obs = _observability_from_result(result)
    assert obs["tool_calls"] == [{
        "tool_name": "submit_application",
        "input_redacted": {"company": "字节"},
        "output_summary": None,
        "status": "awaiting_confirmation",
        "duration_ms": None,
        "requires_hitl": True,
        "hitl_status": "pending",
        "error_type": None,
        "error_summary": None,
    }]


def test_real_runtime_bound_hitl_tool_is_blocked_and_persisted() -> None:
    """生产 Runtime 的 matcher 真实绑定投递工具，HITL 短路后写入 run tool-call。

    这里刻意不用 API FakeRuntime：验证 ``CareerCrewRuntime._make_tools`` 的实际
    注册、``build_agent/run_agent`` 的调用链，以及 ``_finish_chat_turn`` 的持久化闭环。
    """
    from careercrew_api.runtime import CareerCrewRuntime, _observability_from_result
    from careercrew_core.conversation.db import FakeConversationDb
    from careercrew_core.conversation.store import ConversationStore
    from careercrew_core.memory.db import FakeMemoryDb
    from careercrew_core.memory.episodic import EpisodicMemory
    from careercrew_core.memory.router import MemoryRouter

    memory_db = FakeMemoryDb()
    rt = CareerCrewRuntime()
    rt._initialized = True  # 仅跳过重组件加载；以下均为生产 Runtime 所需的显式依赖。
    rt.memory_db = memory_db
    rt.memory_router = MemoryRouter()
    rt.multimodal_search = object()
    rt.embedding = None  # vectorize 关闭时 _make_vector_index 的正常降级路径
    rt.conversation_store = ConversationStore(FakeConversationDb())
    rt.settings = SimpleNamespace(
        llm=SimpleNamespace(model="test-model"),
        memory=SimpleNamespace(episodic=SimpleNamespace(vectorize=False)),
        tools=SimpleNamespace(
            registry=SimpleNamespace(
                internal=["rag_query", "memory_search", "memory_write", "profile_update",
                          "search_jobs", "salary_query", "read_image", "submit_application"],
                mcp=[],
            ),
            hitl=SimpleNamespace(requires_confirmation=["submit_application"]),
        ),
    )
    episodic = EpisodicMemory(memory_db, user_id="u-production", thread_id="hitl-production")
    effective = rt.compute_effective_tools("matcher", ["submit_application"])
    registry = rt._make_tools("matcher", episodic=episodic, allowed=effective)
    assert registry.list_names() == ["submit_application"]

    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("submit_application", {
            "company": "字节", "title": "大模型工程师",
        })]),
        AIMessage(content="等待确认后才能投递"),
    ])
    agent = build_agent(
        llm=llm, tools=registry.bindable_tools(), system_prompt="sys", max_iterations=5,
        hitl_requires=rt._hitl_requires(),
    )
    result = run_agent(agent, [HumanMessage(content="投递字节")])
    assert result.blocked_tool_calls == [{
        "name": "submit_application",
        "args": {"company": "字节", "title": "大模型工程师"},
    }]

    ctx = rt._begin_chat_turn(
        "hitl-production", "u-production", module="matcher", agent_id="job_matcher",
        user_text="投递字节", effective_tools=effective,
    )
    rt._finish_chat_turn(ctx, result.content, tool_calls=_observability_from_result(result)["tool_calls"])
    calls = [c for c in rt.conversation_store._db._tool_calls.values() if c["run_id"] == ctx.run_id]
    assert len(calls) == 1
    assert calls[0]["status"] == "awaiting_confirmation"
    assert calls[0]["hitl_status"] == "pending"
    assert calls[0]["requires_hitl"] is True
