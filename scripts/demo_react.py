"""阶段 B 可视化 demo：用真实 DeepSeek-V4-Flash 跑 ReAct 循环 + 工具调用。

跑法：conda run -n careercrew python scripts/demo_react.py
展示：
  1) supervisor 路由表（stage -> agent）—— B3
  2) BaseAgent 跑 ReAct：LLM 思考 -> 调工具 -> 工具返回 -> 综合最终答案（每轮可见）—— B2/B4/B5
  3) Phase A：load_settings + create_llm 用真实硅基流动 key 跑通

这是 pytest 之外的「肉眼验收」：能看到 agent 真的在调工具、用工具结果作答。
"""
from __future__ import annotations

import json

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from careercrew_ai.llm import create_llm
from careercrew_core.agents.base_agent import BaseAgent
from careercrew_core.state.settings import load_settings
from careercrew_core.state.thread_state import STAGES
from careercrew_core.supervisor.router import route
from careercrew_core.tools.registry import ToolRegistry, ToolSpec


# ── mock 工具：职位搜索（真实 RAG/mcp-jobs 在 E 阶段接） ──


@tool
def search_jobs(direction: str, top_k: int = 3) -> str:
    """按求职方向搜索职位 JD（demo 用 mock 数据）。

    Args:
        direction: 求职方向（如"大模型应用"）。
        top_k: 返回条数。
    """
    mock_db = [
        {"company": "字节跳动", "title": "大模型应用工程师",
         "jd": "负责 Agent 应用开发，LangChain/LangGraph，RAG 系统，Python"},
        {"company": "阿里", "title": "算法工程师-大模型",
         "jd": "大模型微调，RAG 检索系统，多模态，Python/PyTorch"},
        {"company": "美团", "title": "后端开发工程师-Java+大模型",
         "jd": "Java 后端 + LLM 应用集成，Agent 编排，Spring Boot"},
        {"company": "腾讯", "title": "大模型应用开发",
         "jd": "LLM 应用，Function Calling，RAG，多智能体协同"},
    ]
    return json.dumps(mock_db[:top_k], ensure_ascii=False)


def show_routing() -> None:
    print("=" * 64)
    print("1) supervisor 路由表（stage -> agent）—— B3")
    print("=" * 64)
    for stage in STAGES:
        print(f"  {stage:12s} -> {route({'stage': stage})}")
    print(f"  {'(未知)':12s} -> {route({'stage': 'xxx'})}")


def show_react() -> None:
    print("\n" + "=" * 64)
    print("2) BaseAgent 跑 ReAct（真实 DeepSeek-V4-Flash）—— B2/B4/B5")
    print("=" * 64)

    settings = load_settings()
    llm = create_llm(settings, max_tokens=512)
    print(f"LLM: {settings.llm.model}\n")

    reg = ToolRegistry()
    reg.register(ToolSpec(tool=search_jobs))

    agent = BaseAgent(
        name="job_matcher",
        system_prompt=(
            "你是 CareerCrew 的职位匹配官。根据用户的求职方向，必须调用 search_jobs 工具"
            "搜索职位，然后简要列出匹配的岗位（公司/ title / 为什么匹配）。用中文，简洁。"
        ),
        llm=llm,
        tools=reg,
        max_iterations=5,
    )

    query = "我是大模型应用/Agent 方向，有 Java 后端背景，帮我找 3 个匹配岗位"
    print(f"用户: {query}\n")

    state = {
        "thread_id": "demo", "user_id": "u1", "stage": "match", "user_intent": query,
        "messages": [HumanMessage(content=query)],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)

    # 逐轮打印 ReAct trace
    for it in agent.last_result.iterations:
        print(f"--- 轮次 {it.iteration + 1} ---")
        if it.content:
            print(f"  思考: {it.content}")
        for tc, tr in zip(it.tool_calls, it.tool_results):
            print(f"  调工具: {tc['name']}({tc['args']})")
            print(f"  工具返回: {tr}")
        if not it.tool_calls:
            print("  (无工具调用 -> 最终答案)")
        print()

    print("=" * 64)
    print("最终答案:")
    print(agent.last_result.content)
    print("=" * 64)
    r = agent.last_result
    print(f"统计: {len(r.iterations)} 轮, {r.tool_calls_total} 次工具调用, 停止原因={r.stopped_reason}")


if __name__ == "__main__":
    show_routing()
    show_react()
