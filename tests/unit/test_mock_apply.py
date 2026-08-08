"""K1 高风险工具测试：requires_confirmation 标记 + 执行。"""
from __future__ import annotations

from careercrew_core.tools.mcp.mock_apply import (
    HIGH_RISK_TOOLS,
    accept_offer,
    register_high_risk_tools,
    salary_talk_script,
    send_greeting,
    submit_application,
)
from careercrew_core.tools.registry import ToolRegistry, ToolSpec


def test_high_risk_tools_list() -> None:
    assert {t.name for t in HIGH_RISK_TOOLS} == {
        "submit_application", "send_greeting", "accept_offer", "salary_talk_script",
    }


def test_register_high_risk_marks_confirmation() -> None:
    reg = ToolRegistry()
    register_high_risk_tools(reg)
    assert set(reg.high_risk_names()) == {
        "submit_application", "send_greeting", "accept_offer", "salary_talk_script",
    }


def test_execute_high_risk_tools() -> None:
    reg = ToolRegistry()
    register_high_risk_tools(reg)
    assert "已投递" in reg.execute("submit_application", company="字节", title="大模型工程师")
    assert "已接受" in reg.execute("accept_offer", company="字节", salary="35K")
    assert "谈薪话术" in reg.execute("salary_talk_script", company="字节", target_salary="40K")
