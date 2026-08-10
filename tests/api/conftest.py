"""API 测试 fixtures：FakeRuntime 注入 + web marker。

FakeRuntime duck-types CareerCrewRuntime，不触发任何重组件初始化。
测试用 ``app.dependency_overrides[get_runtime_dep] = lambda: FakeRuntime()`` 无缝换 fake。
"""
from __future__ import annotations

from collections.abc import Callable

import pytest


class FakeRuntime:
    """测试用假运行时（duck-typed，不初始化重组件）。"""

    def __init__(self) -> None:
        self._initialized = True
        self.match_output = "匹配到字节跳动 0.95 / 腾讯 0.85"
        self.resume_output = "定制简历完成，匹配度 0.97"
        self.interview_output = "1. 请讲讲你对 RAG 的理解\n2. 如何优化召回质量？"
        self.score_result = {"score": 8.5, "feedback": "回答结构清晰，可补充具体案例"}
        self.consult_opinions = {
            "salary_negotiator": "建议薪资 30-35K",
            "career_planner": "建议先积累 Agent 项目经验",
        }
        self.consult_synthesis = "综合建议：先积累经验，谈薪 30-35K"
        self.match_chunks: list[str] = []
        self.resume_chunks: list[str] = []
        self.upload_content = "解析出的简历文本内容"
        self.knowledge_docs: list[dict] = [
            {"doc": "note", "source": "data/uploads/note.md", "points": 3}
        ]

    def health_info(self) -> dict:
        return {
            "status": "ok", "model": "fake-model", "embedding": "fake",
            "vector_store": "fake", "ready": True,
        }

    def get_cycle(self, thread_id: str, user_id: str = "u_001"):
        class FakeCycle:
            def __init__(self_inner):
                self_inner.job_matcher = None
                self_inner.resume_advisor = None

            def run_match(self_inner, intent: str) -> str:
                if self_inner.job_matcher:
                    self_inner.job_matcher.run(None)
                return self.match_output

            def run_resume(self_inner, jd_text: str) -> str:
                if self_inner.resume_advisor:
                    self_inner.resume_advisor.run(None)
                return self.resume_output
        return FakeCycle()

    def run_match_stream(self, thread_id: str, user_id: str, intent: str,
                         cb: Callable[[str], None] | None = None) -> str:
        if cb:
            cb(self.match_output)
        return self.match_output

    def run_resume_stream(self, thread_id: str, user_id: str, jd_text: str,
                          cb: Callable[[str], None] | None = None) -> str:
        if cb:
            cb(self.resume_output)
        return self.resume_output

    def new_job_matcher(self, cb: Callable[[str], None] | None = None, episodic=None):
        class FakeAgent:
            def __init__(self_inner):
                self_inner.last_result = type("R", (), {"content": self.match_output})()

            def run(self_inner, state):
                if cb:
                    cb(self.match_output)
        return FakeAgent()

    def new_resume_advisor(self, cb: Callable[[str], None] | None = None, episodic=None):
        class FakeAgent:
            def __init__(self_inner):
                self_inner.last_result = type("R", (), {"content": self.resume_output})()

            def run(self_inner, state):
                if cb:
                    cb(self.resume_output)
        return FakeAgent()

    def new_interviewer(self, cb: Callable[[str], None] | None = None, episodic=None):
        class FakeAgent:
            def __init__(self_inner):
                self_inner.last_result = type("R", (), {"content": self.interview_output})()

            def run(self_inner, state):
                if cb:
                    cb(self.interview_output)
        return FakeAgent()

    def new_consult_agent(self, name: str, cb: Callable[[str], None] | None = None, episodic=None):
        output = self.consult_opinions.get(name, "无意见")

        class FakeAgent:
            def __init__(self_inner):
                self_inner.last_result = type("R", (), {"content": output})()

            def run(self_inner, state):
                if cb:
                    cb(output)
        return FakeAgent()

    def _get_episodic(self, thread_id: str, user_id: str = "u_001"):
        return None  # FakeRuntime 不需要真实 episodic

    def get_threads(self, user_id: str = "u_001") -> list[dict]:
        return [{"thread_id": "m1", "title": "测试对话", "entries": 3}]

    @property
    def llm(self):
        """假 LLM（_synthesize 调 .invoke）。"""
        class FakeLLM:
            def invoke(self_inner, prompt, config=None):
                return type("R", (), {"content": self.consult_synthesis})()
        return FakeLLM()

    def score_answer(self, question: str, answer: str, max_score: int = 10) -> dict:
        return self.score_result

    def record_interview_qa(self, entries: list[dict]) -> int:
        return len(entries)

    def read_image(self, path: str) -> str:
        return self.upload_content

    def load_document(self, path: str) -> str:
        return self.upload_content

    def ingest_document(self, path: str, metadata: dict | None = None) -> dict:
        from pathlib import Path

        return {"doc_id": Path(path).stem, "points": 2, "path": path}

    def delete_document(self, doc_id: str) -> int:
        return 3

    def knowledge_status(self) -> dict:
        return {"points": sum(d["points"] for d in self.knowledge_docs), "docs": self.knowledge_docs}

    def consult_stream(self, names: list[str], question: str, user_id: str,
                       cb: Callable[[str, str], None] | None = None):
        if cb:
            for name in names:
                cb(name, self.consult_opinions.get(name, "无意见"))
        return {"opinions": self.consult_opinions, "synthesis": self.consult_synthesis}


@pytest.fixture
def fake_runtime() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture
def client(fake_runtime: FakeRuntime):
    """TestClient with FakeRuntime injected via dependency_overrides."""
    from fastapi.testclient import TestClient

    from careercrew_api.deps import get_runtime_dep
    from careercrew_api.main import create_app

    app = create_app()
    app.dependency_overrides[get_runtime_dep] = lambda: fake_runtime
    return TestClient(app)
