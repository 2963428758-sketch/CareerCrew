"""VLM 看图回答测试（离线：OpenAI client mock）。"""
from __future__ import annotations

from careercrew_ai.vector_store import QueryResult
from careercrew_core.rag.vlm_answer import vlm_answer
from careercrew_core.state.settings import Settings


def test_vlm_answer_sources_and_fallback(valid_config_data: dict, monkeypatch) -> None:
    class FakeCompletions:
        def create(self, **kwargs):
            raise RuntimeError("no network")

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            pass

        @property
        def chat(self):
            return FakeChat()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    settings = Settings.model_validate(valid_config_data)
    results = [
        QueryResult(id="a", score=0.9, text="简历要点", metadata={"doc": "r"})
    ]
    out = vlm_answer(settings, "这个简历怎么样", results, llm=None)
    assert out["sources"][0]["id"] == "a"
    assert out["sources"][0]["doc"] == "r"
    assert "不可用" in out["answer"]  # VLM 失败且无 llm 回退
