"""F resume_advisor 测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.agents.resume_advisor import ResumeAdvisor, resume_match_score
from careercrew_core.tools.internal.rag_query import make_rag_query_tool
from careercrew_core.tools.registry import ToolRegistry, ToolSpec
from tests.fakes import FakeChatModel


def test_resume_match_score_perfect() -> None:
    jd = "要求 Python、LangChain、RAG、Agent，熟悉向量数据库"
    resume = "精通 Python，用 LangChain 搭 RAG 系统，做过 Agent 应用，熟悉向量检索与 Milvus"
    assert resume_match_score(resume, jd) == 1.0


def test_resume_match_score_partial() -> None:
    jd = "要求 Python、LangChain、Java、Spring"
    resume = "Python 和 LangChain 有项目经验"
    # JD 技能: python, langchain, java, spring -> resume 命中 python, langchain = 2/4
    # 注: naive 子串打分不处理否定("不会 Java")与同义词("Milvus" vs "向量"),L1 用 Ragas 补语义
    assert resume_match_score(resume, jd) == 0.5


def test_resume_match_score_empty() -> None:
    assert resume_match_score("", "需要 Python") == 0.0
    assert resume_match_score("会 Python", "") == 0.0
    # JD 无已知技能
    assert resume_match_score("会 Python", "招聘工程师，待遇从优") == 0.0


def _tc(name, args, id_="1"):
    return {"name": name, "args": args, "id": id_, "type": "tool_call"}


def test_resume_advisor_runs_with_rag_query() -> None:
    """ResumeAdvisor 应能调用 rag_query 检索简历范本再定制。"""
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("rag_query", {"query": "大模型应用工程师简历怎么写", "top_k": 2}, "c1")]),
        AIMessage(content="已按 JD 定制简历，匹配度 0.9"),
    ])
    class FakeHS:
        def search(self, query, top_k=5, filters=None):
            from careercrew_ai.vector_store import QueryResult
            return [QueryResult(id="r1", score=0.99, text="简历要点：量化描述、突出 RAG/Agent 项目", metadata={})]
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=make_rag_query_tool(FakeHS())))
    agent = ResumeAdvisor(llm=llm, tools=reg, max_iterations=5)
    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "resume", "user_intent": "定制简历",
        "messages": [HumanMessage(content="按字节大模型应用工程师 JD 定制简历")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)
    assert agent.last_result.content == "已按 JD 定制简历，匹配度 0.9"
    # 调用了 rag_query（1 次工具调用）
    assert agent.last_result.tool_calls_total == 1
