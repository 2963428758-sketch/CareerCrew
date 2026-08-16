"""effective_tools 交集纯函数（T3.5 §16.3）。

服务端最终集合：
    effective_tools =
        client_requested_tools ∩ server_allowlist ∩ role_allowlist ∩ module_allowlist

任何一项不允许都不能调用。纯函数、无 IO、无副作用，便于矩阵单测与复用。
"""
from __future__ import annotations


def compute_effective_tools(
    client_requested: list[str] | None,
    server_allowlist: list[str] | None,
    role_allowlist: list[str] | None = None,
    module_allowlist: list[str] | None = None,
) -> list[str]:
    """计算本轮最终可用工具集合（去重、保序，按 client 顺序）。

    语义：
    - ``client_requested`` 为 None 或空 → 视为「未选择」，默认放行整个服务端允许集
      （即 server ∩ role ∩ module），保持既有行为不变（§16.2/16.3 默认全放行）。
    - 三个 allowlist 为 None 时视为「不约束」（放行全部），空列表同样视为不约束
      （与本代码库 None/空 = 默认放行的惯例一致）。
    - 交集结果保持 client 提交顺序，去重；不在任何 allowlist 的 client 项被裁剪。

    返回有序去重的工具 id 列表。
    """
    server = set(server_allowlist or [])
    role = set(role_allowlist) if role_allowlist is not None else None
    module = set(module_allowlist) if module_allowlist is not None else None

    # 未选择：默认放行整个服务端允许集（再按 role/module 裁剪）
    requested = client_requested or None
    base: set[str]
    if requested is None or len(requested) == 0:
        base = set(server)
    else:
        base = set(requested) & server

    if role is not None:
        base &= role
    if module is not None:
        base &= module

    # 保序输出：以 client 顺序为主；未选择时按 server_allowlist 顺序
    order = requested if requested else list(server_allowlist or [])
    seen: set[str] = set()
    out: list[str] = []
    for name in order:
        if name in base and name not in seen:
            seen.add(name)
            out.append(name)
    # server 中存在的但在 order 之外（理论上不会发生，防御性补齐）
    for name in sorted(base - seen):
        out.append(name)
    return out
