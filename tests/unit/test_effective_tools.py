"""T3.5 effective_tools 交集纯函数 + capabilities 汇总测试（TDD）。"""
from __future__ import annotations

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
