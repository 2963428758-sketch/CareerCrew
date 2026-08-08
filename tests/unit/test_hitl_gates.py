"""G3 HITL 闸门测试。"""
from __future__ import annotations

from careercrew_cli.hitl.gates import HitlGates
from careercrew_ui.cli.renderer import Renderer


def _gates(answer: str) -> HitlGates:
    return HitlGates(renderer=Renderer(), input_fn=lambda _: answer)


def test_confirm_yes() -> None:
    assert _gates("y").confirm("投递简历") is True
    assert _gates("yes").confirm("投递简历") is True


def test_confirm_no() -> None:
    assert _gates("n").confirm("接 offer") is False
    assert _gates("no").confirm("接 offer") is False


def test_confirm_default_no() -> None:
    """回车（空输入）= 默认拒绝（安全默认）。"""
    assert _gates("").confirm("投递") is False
