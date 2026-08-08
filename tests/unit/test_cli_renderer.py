"""G1 CLI 渲染层测试。"""
from __future__ import annotations

from careercrew_ui.cli.renderer import Renderer


def test_banner(capsys) -> None:
    Renderer().banner()
    assert "CareerCrew" in capsys.readouterr().out


def test_show_agent(capsys) -> None:
    Renderer().show_agent("job_matcher", "匹配结果")
    out = capsys.readouterr().out
    assert "job_matcher" in out
    assert "匹配结果" in out


def test_show_user_and_status(capsys) -> None:
    r = Renderer()
    r.show_user("帮我找工作")
    r.show_status("匹配中...")
    out = capsys.readouterr().out
    assert "帮我找工作" in out
    assert "匹配中" in out


def test_show_error(capsys) -> None:
    Renderer().show_error("处理失败")
    assert "处理失败" in capsys.readouterr().out
