"""N5 场景 3：HITL 投递闭环 谈薪建议 -> 高风险拦截 -> 确认后真实执行。

真实组件串联（LLM 用 FakeChatModel 预编排响应）：
build_agent + HitlMiddleware（block-and-record，T3.5）
-> submit_application 被拦：不执行 + blocked_tool_calls 留痕
-> 用户确认后（去掉 HITL 配置重发，等价 API 层确认后的新一轮）工具真实执行
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from careercrew_ai.agents.langchain_agent import build_agent, run_agent
from careercrew_core.tools.mcp.mock_apply import submit_application
from tests.fakes import FakeChatModel


def _tc(name: str, args: dict, id_: str = "c1") -> dict:
    return {"name": name, "args": args, "id": id_, "type": "tool_call"}


@pytest.mark.e2e
def test_apply_hitl_flow_block_then_confirmed_execute() -> None:
    # ── 第 1 步：谈薪建议（SalaryNegotiator 风格产出先于投递动作） ──
    salary_llm = FakeChatModel([AIMessage(content="建议报价 25k-30k：低于你的期望区间下限……")])
    advisor = build_agent(salary_llm, tools=None, system_prompt="你是薪资谈判顾问")
    r1 = run_agent(advisor, [HumanMessage(content="字节给了 22k，帮我谈薪")])
    assert "25k" in r1.content

    # ── 第 2 步：agent 发起投递 -> HITL 拦截（工具未执行 + 留痕待确认） ──
    executed: list[str] = []

    def _submit(company: str, title: str = "", resume: str = "") -> str:
        executed.append(company)
        return submit_application.invoke({"company": company})

    llm_want_apply = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("submit_application", {"company": "字节跳动"})]),
        AIMessage(content="无法投递，需要用户确认。"),
    ])
    guarded = build_agent(
        llm_want_apply, tools=[submit_application],
        system_prompt="求职助手", hitl_requires={"submit_application"},
    )
    r2 = run_agent(guarded, [HumanMessage(content="确认后帮我投递字节")])
    assert executed == []                       # 高风险工具未执行
    assert guarded._hitl.blocked_tool_calls == [
        {"name": "submit_application", "args": {"company": "字节跳动"}},
    ]
    assert "需要用户确认" in r2.content          # 拦截 ToolMessage 回喂后的兜底话术

    # ── 第 3 步：用户确认（API 层为前端确认后发起新一轮），工具真实执行 ──
    from langchain_core.tools import tool

    @tool("submit_application")
    def do_apply(company: str) -> str:
        """Submit job application (confirmed)."""
        executed.append(company)
        return f"已向 {company} 投递"

    confirmed = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("submit_application", {"company": "字节跳动"}, id_="c2")]),
        AIMessage(content="已为你完成投递。"),
    ])
    unguarded = build_agent(confirmed, tools=[do_apply], system_prompt="求职助手")
    r3 = run_agent(unguarded, [HumanMessage(content="我确认投递字节")])
    assert executed == ["字节跳动"]              # 确认路径上工具执行一次
    assert "投递" in r3.content
