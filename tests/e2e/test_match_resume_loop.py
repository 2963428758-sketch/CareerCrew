"""G4 M1 闭环 E2E 冒烟（注入 fake agent）。"""
from __future__ import annotations

import pytest

from careercrew_core.workflow.job_cycle import JobCycle


class FakeAgent:
    def __init__(self, content: str) -> None:
        self.last_result = type("R", (), {"content": content})()
        self.run_calls = 0

    def run(self, state) -> None:
        self.run_calls += 1


@pytest.mark.e2e
def test_match_resume_loop() -> None:
    """意向 -> 匹配 -> 选 JD -> 简历，M1 验收链路。"""
    jm = FakeAgent("1. 字节 大模型应用工程师 0.95\n2. 腾讯 大模型应用开发 0.85")
    ra = FakeAgent("定制简历：突出 RAG/Agent 项目，匹配度 0.95")
    cycle = JobCycle(jm, ra, user_id="u1")
    out = cycle.run(
        "我是大模型应用方向，帮我找工作并定制简历",
        user_id="u1",
        select_jd=lambda _m: "字节 大模型应用工程师 JD：Agent 应用开发/RAG/Python",
    )
    assert "匹配度" in out
    assert jm.run_calls == 1 and ra.run_calls == 1
