"""G2 JobCycle 工作流测试（注入 fake agent）。"""
from __future__ import annotations

from careercrew_cli.workflow.job_cycle import JobCycle
from careercrew_ui.cli.renderer import Renderer


class FakeAgent:
    def __init__(self, content: str) -> None:
        self._content = content
        self.last_result = type("R", (), {"content": content})()
        self.run_calls = 0

    def run(self, state) -> None:
        self.run_calls += 1


def test_job_cycle_full_flow() -> None:
    jm = FakeAgent("匹配到字节 0.95 / 腾讯 0.85")
    ra = FakeAgent("定制简历完成，匹配度 0.97")
    cycle = JobCycle(jm, ra, renderer=Renderer())

    def select_jd(match_out: str) -> str:
        assert "字节" in match_out
        return "字节跳动 大模型应用工程师 JD：Agent/RAG/Python"

    out = cycle.run("我是大模型方向，有 Java 背景，帮我找工作并定制简历", select_jd=select_jd)
    assert out == "定制简历完成，匹配度 0.97"
    assert jm.run_calls == 1
    assert ra.run_calls == 1


def test_job_cycle_skip_resume() -> None:
    jm = FakeAgent("匹配结果")
    ra = FakeAgent("简历")
    cycle = JobCycle(jm, ra, renderer=Renderer())
    out = cycle.run("帮我找工作", select_jd=lambda _out: None)  # 跳过简历
    assert out == "匹配结果"
    assert ra.run_calls == 0


def test_run_match_only() -> None:
    jm = FakeAgent("匹配结果")
    cycle = JobCycle(jm, FakeAgent("x"), renderer=Renderer())
    assert cycle.run_match("我的方向是大模型") == "匹配结果"
    assert jm.run_calls == 1


def test_run_resume_only() -> None:
    ra = FakeAgent("简历完成")
    cycle = JobCycle(FakeAgent("x"), ra, renderer=Renderer())
    assert cycle.run_resume("某 JD 内容") == "简历完成"
    assert ra.run_calls == 1
