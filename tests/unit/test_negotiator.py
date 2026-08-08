"""J1/J2 薪资谈判师测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.agents.salary_negotiator import SalaryNegotiator
from careercrew_core.tools.internal.rag_query import make_rag_query_tool
from careercrew_core.tools.registry import ToolRegistry, ToolSpec


class FakeChatModel:
    def __init__(self):
        self._i = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages, config=None):
        if self._i == 0:
            self._i += 1
            return AIMessage(content="", tool_calls=[{"name": "rag_query", "args": {"query": "大模型工程师 薪资 谈判", "top_k": 3}, "id": "c1", "type": "tool_call"}])
        return AIMessage(content="谈薪策略：报价 35-40K，筹码是有字节 offer 竞争。")


class FakeHS:
    def search(self, query, top_k=5, filters=None):
        from careercrew_ai.vector_store import QueryResult
        return [QueryResult(id="r1", score=0.9, text="大模型工程师 薪资 30-45K，谈薪技巧：先报价、有 offer 竞争可抬", metadata={})]


def test_negotiator_rag_query_then_strategy() -> None:
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=make_rag_query_tool(FakeHS())))
    agent = SalaryNegotiator(llm=FakeChatModel(), tools=reg, max_iterations=5)
    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "negotiate", "user_intent": "帮我谈字节 offer 薪资",
        "messages": [HumanMessage(content="字节 offer 35K，帮我谈")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)
    assert "报价" in agent.last_result.content
    assert agent.last_result.tool_calls_total == 1
