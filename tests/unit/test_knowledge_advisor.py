"""知识库问答 agent 单测：name / prompt 文件 / 兜底文案。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.agents.knowledge_advisor import (
    KnowledgeAdvisor,
    _DEFAULT_PROMPT,
    _PROMPT_PATH,
)
from tests.fakes import FakeChatModel


def test_knowledge_advisor_name_and_prompt_file() -> None:
    path = _PROMPT_PATH
    assert path.exists(), "知识库顾问 prompt 文件应存在"
    prompt = path.read_text(encoding="utf-8")
    assert "rag_query" in prompt

    agent = KnowledgeAdvisor(
        llm=FakeChatModel([AIMessage(content="RAG 检索流程包括解析、切分、向量化与检索。")]),
    )
    assert agent.name == "knowledge_advisor"
    assert agent.system_prompt == prompt

    state = {
        "thread_id": "t1", "user_id": "u1", "stage": "knowledge", "user_intent": "RAG 检索流程",
        "messages": [HumanMessage(content="RAG 检索流程是什么？")],
        "pending_action": None, "agent_outputs": {}, "target_companies": [],
    }
    agent.run(state)
    assert "解析" in agent.last_result.content
    assert agent.last_result.stopped_reason == "final_answer"


def test_knowledge_advisor_fallback_prompt(tmp_path) -> None:
    missing = tmp_path / "missing.txt"
    agent = KnowledgeAdvisor(llm=FakeChatModel([]), prompt_path=missing)
    assert agent.system_prompt == _DEFAULT_PROMPT
