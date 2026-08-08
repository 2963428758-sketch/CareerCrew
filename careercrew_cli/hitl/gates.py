"""HITL 人工闸门（G3）。

高 stakes 动作（投递/接 offer/谈薪）默认确认且默认拒绝（安全默认）。
input_fn 注入便于测试。
"""
from __future__ import annotations

from collections.abc import Callable

from careercrew_ui.cli.renderer import Renderer


class HitlGates:
    """人工闸门：高风险动作确认。默认拒绝。"""

    def __init__(self, renderer: Renderer | None = None, input_fn: Callable[[str], str] = input) -> None:
        self._renderer = renderer or Renderer()
        self._input = input_fn

    def confirm(self, action: str, description: str = "") -> bool:
        """确认高风险动作。默认拒绝（安全默认）。返回 True=确认，False=拒绝。"""
        desc = f"（{description}）" if description else ""
        while True:
            ans = self._input(f"  确认 {action}{desc}? [y/N] ").strip().lower()
            if ans in ("y", "yes"):
                return True
            if ans in ("n", "no", ""):
                return False
            print("  请输入 y/n")
