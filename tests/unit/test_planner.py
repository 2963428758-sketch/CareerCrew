"""J3 职业规划师测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.agents.career_planner import CareerPlanner
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.semantic import SemanticFactStore
from careercrew_core.tools.internal.profile_update import make_profile_update_tool
from careercrew_core.tools.registry import ToolRegistry, ToolSpec
from tests.fakes import FakeChatModel


def test_planner_updates_profile() -> None:
    um = SemanticFactStore(FakeMemoryDb(), user_id="u1")
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=make_profile_update_tool(um, user_id="u1")))
    agent = CareerPlanner(
        llm=FakeChatModel([
            AIMessage(content="", tool_calls=[
                {"name": "profile_update", "args": {"fields": {"profile.skills": ["Python", "RAG"], "profile.direction": "大模型应用"}}, "id": "c1", "type": "tool_call"}
            ]),
            AIMessage(content="规划完成：冲刺字节/阿里，匹配美团/腾讯，阶段 0-3 月补 RAG 深度"),
        ]),
        tools=reg, max_iterations=5,
    )
    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "planning", "user_intent": "帮我做职业规划",
        "messages": [HumanMessage(content="我是 Python 方向，想做 Agent 应用，帮我规划")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)
    assert "规划完成" in agent.last_result.content
    # profile_update 已结构化写入
    model = um.load("u1")
    assert "Python" in model.profile.skills
    assert model.profile.direction == "大模型应用"


def test_planner_prompt_includes_salary_query() -> None:
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "careercrew_ai" / "prompts" / "career_planner.txt"
    text = path.read_text(encoding="utf-8")
    assert "salary_query" in text
    assert "最多 2 次" in text
    assert "工具按需使用，禁止为“可能有用”而预取" in text
    assert "回答中必须使用其结果" in text
    assert "可规划的结构化请求" in text
    assert "本轮必须直接交付所要求的画像、公司池和/或阶段计划" in text
    assert "用户明确请求薪资、薪资谈判或薪酬市场校准" in text
    assert "不得向用户转述检索或工具调用过程" in text


def test_planner_prompt_salary_fact_boundary() -> None:
    """P3 无来源薪资区间：未经 salary_query 结果禁止给出具体数字/区间。"""
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "careercrew_ai" / "prompts" / "career_planner.txt"
    text = path.read_text(encoding="utf-8")
    assert "未经 `salary_query` 结果，禁止在回答中出现任何具体薪资数字或区间" in text
    assert "只能定性描述或标注“待确认”" in text
    # 旧措辞曾鼓励在阶段规划里写薪资区间，必须已被替换
    assert "结合真实薪资区间给出合理预期" not in text


def test_planner_prompt_forbids_pseudo_tool_call_text() -> None:
    """P2 伪工具调用文本泄漏：正文严禁出现调用语法与过程叙述。"""
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "careercrew_ai" / "prompts" / "career_planner.txt"
    text = path.read_text(encoding="utf-8")
    assert "回答正文中严禁输出 `<call>`、`<arg>`、`tool_call` 等任何调用语法" in text
    assert "不得以“先检索/查询”为由中断或推迟回答" in text
    assert "即使历史记录中出现过这类文本" in text
    assert "所需工具不可用时，直接基于已有信息完成交付" in text
