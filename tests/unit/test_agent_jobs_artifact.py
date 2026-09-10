"""search_jobs content_and_artifact 端到端：真跑 agent 循环，验证具名结果记录
与岗位提取（artifact 不受工具结果钳制影响）。"""
from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from careercrew_ai.agents.langchain_agent import build_agent, run_agent
from careercrew_core.preparation.jobs_extract import extract_jobs_from_agent_result
from tests.fakes import FakeChatModel


@tool(response_format="content_and_artifact")
def search_jobs(direction: str, top_k: int = 8, realtime: bool = False):
    """按求职方向搜索职位 JD。"""
    jobs = [{
        "company": "测试公司", "title": "Java开发", "city": "深圳",
        "salary": "20-30K", "experience": "3-5年", "source": "boss",
        "source_label": "Boss直聘", "retrieval_mode": "live",
        "retrieval_mode_label": "实时检索",
        "matched_core_terms": ["Java"], "url": "https://example.com/j/1",
        "jd": "负责接口开发" * 2000,  # 超过 6000 字符钳制阈值
    }]
    return json.dumps(jobs, ensure_ascii=False), jobs


def _tc(name: str, args: dict, id_: str = "c1") -> dict:
    return {"name": name, "args": args, "id": id_, "type": "tool_call"}


def test_run_agent_captures_named_artifact_and_extracts_jobs():
    llm = FakeChatModel([
        AIMessage(content="我先搜一下", tool_calls=[_tc("search_jobs", {"direction": "Java"})]),
        AIMessage(content="找到 1 个岗位"),
    ])
    agent = build_agent(llm=llm, tools=[search_jobs], system_prompt="sys", max_iterations=5)
    result = run_agent(agent, [HumanMessage(content="帮我找 Java 工作")])

    assert result.content.endswith("找到 1 个岗位")
    # 具名结果记录：name/tool_call_id 齐全，artifact 不因正文钳制丢失
    named = [r for it in result.iterations for r in it.tool_results_named]
    assert len(named) == 1
    assert named[0]["name"] == "search_jobs"
    assert named[0]["tool_call_id"] == "c1"
    artifact_jobs = named[0]["artifact"]
    assert isinstance(artifact_jobs, list) and artifact_jobs[0]["company"] == "测试公司"
    # 正文被钳制（原始 12274 字符 → ~6000），artifact 完整无损
    assert len(named[0]["content"]) <= 6100

    jobs = extract_jobs_from_agent_result(result)
    assert len(jobs) == 1
    assert jobs[0]["company"] == "测试公司"
    assert jobs[0]["url"] == "https://example.com/j/1"
    assert len(jobs[0]["jd"]) == 12000  # 未被 30000 上限截断，未被 6000 钳制
