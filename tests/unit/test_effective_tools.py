"""T3.5 effective_tools 交集纯函数 + capabilities 汇总测试（TDD）。"""
from __future__ import annotations

from types import SimpleNamespace

from careercrew_core.tools.capabilities import build_capabilities
from careercrew_core.tools.effective import compute_effective_tools

# ── effective_tools 纯函数矩阵（§16.3）──


def test_client_superset_clipped_to_server_allowlist() -> None:
    """client 超集被裁剪到 server allowlist。"""
    out = compute_effective_tools(
        ["rag_query", "secret_tool", "memory_search"],
        ["rag_query", "memory_search", "profile_update"],
    )
    assert out == ["rag_query", "memory_search"]


def test_role_allowlist_clips() -> None:
    out = compute_effective_tools(
        ["rag_query", "memory_search", "profile_update"],
        ["rag_query", "memory_search", "profile_update"],
        role_allowlist=["rag_query", "memory_search"],
    )
    assert out == ["rag_query", "memory_search"]


def test_module_allowlist_clips() -> None:
    out = compute_effective_tools(
        ["rag_query", "read_image", "memory_search"],
        ["rag_query", "read_image", "memory_search"],
        module_allowlist=["rag_query", "read_image"],
    )
    assert out == ["rag_query", "read_image"]


def test_empty_client_means_default_all_allowlist() -> None:
    """client None/空 = 默认放行整个 server allowlist（保持既有行为）。"""
    out = compute_effective_tools(
        None, ["rag_query", "memory_search", "profile_update"],
    )
    assert out == ["rag_query", "memory_search", "profile_update"]
    out2 = compute_effective_tools([], ["rag_query", "memory_search"])
    assert out2 == ["rag_query", "memory_search"]


def test_all_four_layers_intersect() -> None:
    """client ∩ server ∩ role ∩ module 全栈交集。"""
    out = compute_effective_tools(
        ["a", "b", "c", "d"],
        ["a", "b", "c", "d", "e"],
        role_allowlist=["a", "b", "c"],
        module_allowlist=["a", "b"],
    )
    assert out == ["a", "b"]


def test_preserves_client_order_and_dedups() -> None:
    out = compute_effective_tools(
        ["b", "a", "b", "c"],
        ["a", "b", "c"],
    )
    assert out == ["b", "a", "c"]


def test_allowlist_none_means_no_constraint() -> None:
    """role/module allowlist 为 None = 不约束。"""
    out = compute_effective_tools(
        ["a", "b"], ["a", "b", "c"], role_allowlist=None, module_allowlist=None,
    )
    assert out == ["a", "b"]


def test_runtime_policy_removes_memory_tools_before_agent_assembly() -> None:
    """Case 8：用户禁用生成/使用时，最终工具快照不应包含 Memory 工具。"""
    from careercrew_api.runtime import CareerCrewRuntime
    from careercrew_core.memory.db import FakeMemoryDb
    from careercrew_core.memory.policy import MemoryPolicyStore

    db = FakeMemoryDb()
    policy = MemoryPolicyStore(db)
    policy.set_global(enabled=True, generate=True, use=True)
    policy.set_user("u1", enabled=True, generate=False, use=False)
    rt = CareerCrewRuntime()
    rt._initialized = True
    rt.policy_store = policy
    rt.settings = SimpleNamespace(
        memory=SimpleNamespace(enabled=True),
        tools=SimpleNamespace(
            registry=SimpleNamespace(
                internal=["rag_query", "memory_search", "memory_write", "profile_update"],
                mcp=[],
            )
        ),
    )

    effective = rt.compute_effective_tools("matcher", None, user_id="u1")

    assert effective == ["rag_query"]


def test_runtime_policy_can_read_without_generate_tools() -> None:
    from careercrew_api.runtime import CareerCrewRuntime
    from careercrew_core.memory.db import FakeMemoryDb
    from careercrew_core.memory.policy import MemoryPolicyStore

    db = FakeMemoryDb()
    policy = MemoryPolicyStore(db)
    policy.set_global(enabled=True, generate=True, use=True)
    policy.set_user("u1", enabled=True, generate=False, use=True)
    rt = CareerCrewRuntime()
    rt._initialized = True
    rt.policy_store = policy
    rt.settings = SimpleNamespace(
        memory=SimpleNamespace(enabled=True),
        tools=SimpleNamespace(
            registry=SimpleNamespace(
                internal=["rag_query", "memory_search", "memory_write", "profile_update"],
                mcp=[],
            )
        ),
    )

    effective = rt.compute_effective_tools("matcher", None, user_id="u1")

    assert effective == ["rag_query", "memory_search"]


def test_agent_factory_does_not_bind_memory_tools_when_master_is_off() -> None:
    """Case 8 的真实装配接缝：即使调用方未传 allowed，也不能绑定 Memory 工具。"""
    from careercrew_api.runtime import CareerCrewRuntime
    from careercrew_core.memory.db import FakeMemoryDb
    from careercrew_core.memory.episodic import EpisodicMemory
    from careercrew_core.memory.policy import MemoryPolicyStore
    from careercrew_core.memory.router import MemoryRouter
    from careercrew_core.memory.service import MemoryService

    db = FakeMemoryDb()
    policy = MemoryPolicyStore(db)
    policy.set_global(enabled=True)
    policy.set_user("u1", enabled=False)
    rt = CareerCrewRuntime()
    rt._initialized = True
    rt.memory_db = db
    rt.policy_store = policy
    rt.memory_service = MemoryService(db, policy_store=policy, feature_enabled=True)
    rt.embedding = None
    rt.multimodal_search = object()
    rt.memory_router = MemoryRouter()
    rt.settings = SimpleNamespace(
        memory=SimpleNamespace(enabled=True, episodic=SimpleNamespace(vectorize=False)),
        tools=SimpleNamespace(
            registry=SimpleNamespace(
                internal=["rag_query", "memory_search", "memory_write", "profile_update", "search_jobs", "submit_application"],
                mcp=[],
            ),
            hitl=SimpleNamespace(requires_confirmation=[]),
        ),
    )

    tools = rt._make_tools("matcher", episodic=EpisodicMemory(db, "u1", "t1"))

    assert "memory_search" not in tools.list_names()
    assert "memory_write" not in tools.list_names()
    assert "profile_update" not in tools.list_names()


# ── capabilities 汇总（§16.1）──


class _FakeSettings:
    def __init__(self, internal, mcp, hitl):
        self.tools = type("T", (), {
            "registry": type("RG", (), {"internal": internal, "mcp": mcp}),
            "hitl": type("H", (), {"requires_confirmation": hitl}),
        })()


def test_capabilities_shape_and_hitl_flag() -> None:
    s = _FakeSettings(
        ["rag_query", "memory_search"], ["mcp_jobs"],
        ["submit_application", "accept_offer"],
    )
    tools = build_capabilities("chat", s)
    assert tools == [
        {"id": "rag_query", "name": "Knowledge Search", "enabled": True, "requires_hitl": False},
        {"id": "memory_search", "name": "Memory Search", "enabled": True, "requires_hitl": False},
    ]


def test_capabilities_module_allowlist_filters() -> None:
    """module=resume 只暴露声明为 resume 可见的工具。"""
    s = _FakeSettings(
        ["rag_query", "memory_search", "memory_write", "profile_update"], [],
        ["submit_application"],
    )
    tools = build_capabilities("resume", s)
    ids = [t["id"] for t in tools]
    assert "profile_update" in ids
    assert "rag_query" in ids
    # resume 未声明 memory_search/memory_write/salary_query → 裁剪
    assert "memory_search" not in ids
    assert "memory_write" not in ids


def test_capabilities_requires_hitl_flag_set() -> None:
    s = _FakeSettings(["rag_query", "profile_update"], [], ["profile_update"])
    tools = build_capabilities("chat", s)
    by_id = {t["id"]: t for t in tools}
    assert by_id["profile_update"]["requires_hitl"] is True
    assert by_id["rag_query"]["requires_hitl"] is False


# ── Critical 1 / Important 3：MODULE_TOOLS 与 _make_tools(kind) 1:1 对齐 ──


def test_module_tools_align_with_make_tools_branches() -> None:
    """MODULE_TOOLS 声明的每 module 工具集必须严格等于 `_make_tools(kind)` 实际构造集。

    防止默认路径（未传 tools）时 `_server_allowlist`（registry ∩ MODULE_TOOLS）与真正
    bound 的工具集漂移：search_jobs/salary_query/read_image 须在对应 module 中存在，
    且 chat（planner）不得多报未构造的 memory_write/read_image。
    """
    from careercrew_core.tools.capabilities import MODULE_TOOLS

    # `_make_tools` 各 branch 实际 register 的工具名（与 runtime.py 一一对应）
    constructed = {
        "matcher": {"search_jobs", "rag_query", "memory_write", "memory_search",
                    "profile_update", "submit_application"},
        "resume": {"rag_query", "profile_update"},
        "interview": {"rag_query", "memory_write", "memory_search"},
        "salary": {"rag_query", "profile_update", "memory_search", "salary_query"},
        "chat": {"rag_query", "profile_update", "memory_search", "salary_query"},
        "knowledge": {"rag_query", "read_image", "memory_search"},
    }
    for module, names in constructed.items():
        assert set(MODULE_TOOLS[module]) == names, (
            f"MODULE_TOOLS[{module}] 漂移：声明 {set(MODULE_TOOLS[module])}，"
            f"实际构造 {names}"
        )

    # 真正 bound 的特殊工具确实落在声明里（review Critical 1 功能回归点）
    assert "search_jobs" in MODULE_TOOLS["matcher"]
    assert "salary_query" in MODULE_TOOLS["chat"]
    assert "salary_query" in MODULE_TOOLS["salary"]
    assert "read_image" in MODULE_TOOLS["knowledge"]
    assert "submit_application" in MODULE_TOOLS["matcher"]
    # chat=planner 不构造 memory_write/read_image，声明里不得保留（review Important 3）
    assert "memory_write" not in MODULE_TOOLS["chat"]
    assert "read_image" not in MODULE_TOOLS["chat"]


def test_consult_module_tools_are_exact_advisor_union() -> None:
    """consult 的 recorded set 只能包含五位顾问至少一位可实际构造的工具。"""
    from careercrew_core.tools.capabilities import MODULE_TOOLS

    advisor_union = (
        set(MODULE_TOOLS["salary"])
        | set(MODULE_TOOLS["chat"])
        | set(MODULE_TOOLS["matcher"])
        | set(MODULE_TOOLS["resume"])
        | set(MODULE_TOOLS["interview"])
    )
    assert set(MODULE_TOOLS["consult"]) == advisor_union
    assert "read_image" not in MODULE_TOOLS["consult"]
    assert "mcp_jobs" not in MODULE_TOOLS["consult"]
