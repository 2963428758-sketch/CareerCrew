"""客户端 Capability 汇总（T3.5 §16.1）。

GET /api/agent/capabilities?module=chat 由服务端单一事实来源（settings.tools.registry
与 settings.tools.hitl.requires_confirmation）汇总该 module 可见的工具：
    [{"id", "name", "enabled", "requires_hitl"}]

- id：工具稳定标识（对齐 registry 名称）。
- name：人类可读标签（无专用显示名时回退 id）。
- enabled：服务端 allowlist 是否包含该工具（此处恒 True，仅结构上预留禁用位）。
- requires_hitl：是否在 hitl.requires_confirmation（有副作用需人工确认）。

模块 → 工具集合的关系（module_allowlist）由 static MODULE_TOOLS 声明；为空表示
该 module 放行全部注册工具（默认全放行，实现者说明见 report）。
"""
from __future__ import annotations

# 模块显示名 -> 允许的工具 id 集合。用于 capabilities 的服务端 allowlist 分层：
# module_allowlist 更进一步；未列入的 module 视为「不约束」（展示全部注册工具）。
# 这里只做「可见性声明」，不构造工具，因此无需重组件（episodic/向量库）初始化，
# 可在只读状态下汇总服务端事实。
#
# 与 `_make_tools(kind)` 的 per-kind 构造保持 1:1 对齐（kind↔module 映射见下方注释）：
#   matcher→matcher, resume→resume, knowledge→knowledge,
#   interviewer→interview, salary→salary, planner→chat, consult→五位顾问的并集
# 任一 module 声明的集合必须严格等于 `_make_tools` 实际 register 的 tool 名集合，
# 否则 `_server_allowlist`（registry ∩ module）会在默认路径漏裁/多裁，导致
# recorded effective_tools 与真正 bound 的工具集合漂移（review Important 3）。
MODULE_TOOLS: dict[str, list[str]] = {
    # chat=planner：实际构造 rag_query/profile_update/memory_search/salary_query，
    # 不构造 memory_write/read_image——已从声明中移除，避免记录多报。
    "chat": ["rag_query", "memory_search", "profile_update", "salary_query"],
    "matcher": ["search_jobs", "rag_query", "memory_write", "memory_search", "profile_update", "submit_application"],
    "resume": ["rag_query", "profile_update"],
    "knowledge": ["rag_query", "read_image", "memory_search"],
    "interview": ["rag_query", "memory_write", "memory_search"],
    "salary": ["rag_query", "profile_update", "memory_search", "salary_query"],
    # consult 会调度 salary/planner/matcher/resume/interviewer；只声明这些顾问
    # 实际可构造工具的并集，不能把 knowledge-only read_image、MCP 等写入 run。
    "consult": ["rag_query", "memory_search", "memory_write", "profile_update", "search_jobs", "salary_query", "submit_application"],
}

# 工具 id -> 人类可读显示名（未登记回退 id 本身）。
TOOL_LABELS: dict[str, str] = {
    "rag_query": "Knowledge Search",
    "memory_search": "Memory Search",
    "memory_write": "Memory Write",
    "profile_update": "Profile Update",
    "salary_query": "Salary Query",
    "read_image": "Read Image",
    "search_jobs": "Search Jobs",
    "submit_application": "Submit Application",
}


def _registry_names(settings) -> list[str]:
    reg = getattr(getattr(settings, "tools", None), "registry", None)
    if reg is None:
        return []
    internal = list(getattr(reg, "internal", None) or [])
    mcp = list(getattr(reg, "mcp", None) or [])
    seen: set[str] = set()
    names: list[str] = []
    for n in internal + mcp:
        if n not in seen:
            seen.add(n)
            names.append(n)
    return names


def _hitl_names(settings) -> set[str]:
    tools = getattr(settings, "tools", None)
    hitl = getattr(tools, "hitl", None) if tools is not None else None
    return set(getattr(hitl, "requires_confirmation", None) or [])


def build_capabilities(module: str, settings) -> list[dict]:
    """汇总 module 可见工具的有序 capability 列表（服务端单一事实来源）。"""
    allowlist = _registry_names(settings)
    hitl = _hitl_names(settings)
    module_allow = MODULE_TOOLS.get(module)
    tools: list[dict] = []
    for tid in allowlist:
        if module_allow is not None and tid not in module_allow:
            continue
        tools.append({
            "id": tid,
            "name": TOOL_LABELS.get(tid, tid),
            "enabled": True,
            "requires_hitl": tid in hitl,
        })
    return tools
