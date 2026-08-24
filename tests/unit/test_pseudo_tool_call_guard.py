"""伪工具调用文本防护：strip_pseudo_tool_calls / 流式过滤器 / run_agent 集成。

背景（browser QA CP-003 复测观察项 P2）：所需工具被意图级裁剪后，模型会模仿
历史里的调用格式把 ``<call name="rag_query">`` 等当正文输出给用户并就此截断。
真实工具调用走 ``AIMessage.tool_calls`` 结构化通道，本防护只清理正文文本。
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_ai.agents.langchain_agent import (
    PseudoToolCallStreamFilter,
    build_agent,
    run_agent,
    strip_pseudo_tool_calls,
)
from tests.fakes import FakeChatModel

_LEAK = (
    "好的，收到您的信息。基于您3年Java后端经验并希望转型大模型应用工程师的目标，"
    "我将为您制定一份详细的规划。\n\n"
    "首先，我将调用工具来获取一些必要的市场信息，以校准我们的规划。\n\n"
    '<call type="tool" name="rag_query">\n'
    '<arg name="query">大模型应用工程师 转型路径 技能要求 Java后端</arg>\n'
    '<arg name="top_k">3</arg>\n'
    "</call>"
)


def test_strip_removes_full_pseudo_block() -> None:
    cleaned = strip_pseudo_tool_calls(_LEAK)
    assert "<call" not in cleaned
    assert "<arg" not in cleaned
    assert "rag_query" not in cleaned
    # 正文保留
    assert "收到您的信息" in cleaned


def test_strip_keeps_plain_text() -> None:
    text = "## 能力画像\n- 方向：大模型应用\n\n保持原样，不做改写。"
    assert strip_pseudo_tool_calls(text) == text.strip()


def test_strip_truncated_tail_block() -> None:
    text = "规划如下：\n\n<call type=\"tool\" name=\"salary_query\">\n<arg name=\"direction\">AI</arg>"
    cleaned = strip_pseudo_tool_calls(text)
    assert "<call" not in cleaned
    assert "<arg" not in cleaned
    assert "规划如下：" in cleaned


def test_strip_tool_call_variant_tags() -> None:
    text = "结论：<tool_call>{\"name\": \"x\"}</tool_call> 完毕"
    assert strip_pseudo_tool_calls(text) == "结论： 完毕"


def test_stream_filter_blocks_leak_char_by_char() -> None:
    out: list[str] = []
    f = PseudoToolCallStreamFilter(out.append)
    for ch in _LEAK:
        f(ch)
    f.flush()
    joined = "".join(out)
    assert "<call" not in joined
    assert "<arg" not in joined
    assert "收到您的信息" in joined


def test_stream_filter_preserves_normal_text_split_arbitrarily() -> None:
    out: list[str] = []
    f = PseudoToolCallStreamFilter(out.append)
    for ch in "比较 a<b 与 b>c 的大小关系，然后给出 <call 相关的说明也会被扣留吗？":
        f(ch)
    f.flush()
    assert "".join(out) == "比较 a<b 与 b>c 的大小关系，然后给出 "
    # 含 "<call" 的正文同样按伪调用块丢弃（与最终内容净化语义一致）


def test_run_agent_final_content_and_stream_cleaned() -> None:
    streamed: list[str] = []
    llm = FakeChatModel([AIMessage(content=_LEAK)])
    agent = build_agent(llm=llm, tools=None, system_prompt="sys", max_iterations=3)
    result = run_agent(agent, [HumanMessage(content="帮我规划")], stream_callback=streamed.append)
    assert result.content == strip_pseudo_tool_calls(_LEAK)
    assert "<call" not in result.content
    assert "<call" not in "".join(streamed)


def test_run_agent_normal_answer_streams_untouched() -> None:
    streamed: list[str] = []
    llm = FakeChatModel([AIMessage(content="第一段。\n\n第二段。")])
    agent = build_agent(llm=llm, tools=None, system_prompt="sys", max_iterations=3)
    result = run_agent(agent, [HumanMessage(content="hi")], stream_callback=streamed.append)
    assert result.content == "第一段。\n\n第二段。"
    assert "".join(streamed) == "第一段。\n\n第二段。"
