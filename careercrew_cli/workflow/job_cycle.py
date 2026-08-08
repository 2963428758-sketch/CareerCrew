"""求职周期工作流（G2：意向 -> 匹配 -> 简历 部分闭环，M1 验收）。

编排：JobMatcher 找匹配岗位 -> 用户选目标 JD -> ResumeAdvisor 按 JD 定制简历。
agent 依赖注入（测试可传 fake），Renderer 注入。
"""
from __future__ import annotations

from collections.abc import Callable

from langchain_core.messages import HumanMessage

from careercrew_core.agents.job_matcher import JobMatcher
from careercrew_core.agents.resume_advisor import ResumeAdvisor
from careercrew_ui.cli.renderer import Renderer


class JobCycle:
    """M1 闭环编排。"""

    def __init__(
        self,
        job_matcher: JobMatcher,
        resume_advisor: ResumeAdvisor,
        renderer: Renderer | None = None,
    ) -> None:
        self.job_matcher = job_matcher
        self.resume_advisor = resume_advisor
        self.renderer = renderer or Renderer()

    def run_match(self, intent: str, user_id: str = "u_001") -> str:
        """阶段 match：JobMatcher 找匹配岗位，返回最终答案。"""
        state = self._make_state("match", intent, user_id)
        self.job_matcher.run(state)
        return self.job_matcher.last_result.content

    def run_resume(self, jd_text: str, intent: str = "", user_id: str = "u_001") -> str:
        """阶段 resume：ResumeAdvisor 按 JD 定制简历。"""
        query = f"按这个 JD 定制简历：{jd_text}"
        state = self._make_state("resume", query, user_id)
        self.resume_advisor.run(state)
        return self.resume_advisor.last_result.content

    def run(
        self,
        intent: str,
        select_jd: Callable[[str], str | None] | None = None,
        user_id: str = "u_001",
    ) -> str:
        """M1 闭环：匹配 -> 选 JD -> 简历。select_jd 注入 JD 选择（测试 mock），默认交互。"""
        self.renderer.banner()
        self.renderer.show_user(intent)
        self.renderer.show_status("匹配官正在检索岗位并评估匹配度...")
        match_out = self.run_match(intent, user_id)
        self.renderer.show_agent("job_matcher", match_out)

        jd = select_jd(match_out) if select_jd else self._prompt_jd()
        if not jd:
            return match_out

        self.renderer.show_status("简历顾问正在按所选 JD 定制简历...")
        resume_out = self.run_resume(jd, intent, user_id)
        self.renderer.show_agent("resume_advisor", resume_out)
        return resume_out

    def _prompt_jd(self) -> str | None:
        jd = self.renderer.prompt_choice("  输入要定制简历的目标 JD（回车跳过）: ").strip()
        return jd or None

    @staticmethod
    def _make_state(stage: str, intent: str, user_id: str) -> dict:
        return {
            "thread_id": "m1", "user_id": user_id, "stage": stage, "user_intent": intent,
            "messages": [HumanMessage(content=intent)],
            "pending_action": None, "agent_outputs": {}, "target_companies": [],
        }
