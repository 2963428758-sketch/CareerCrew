"""求职周期工作流（G2：意向 -> 匹配 -> 简历 部分闭环，M1 验收）。

编排：JobMatcher 找匹配岗位 -> 用户选目标 JD -> ResumeAdvisor 按 JD 定制简历。

UX 修复：
- 对话历史跨步骤携带（ResumeAdvisor 能看到 JobMatcher 环节用户提供的背景/简历，避免重复问）
- UserModel 画像注入（已有画像则不重复问）
"""
from __future__ import annotations

from collections.abc import Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from careercrew_core.agents.job_matcher import JobMatcher
from careercrew_core.agents.resume_advisor import ResumeAdvisor
from careercrew_ui.cli.renderer import Renderer


class JobCycle:
    def __init__(
        self,
        job_matcher: JobMatcher,
        resume_advisor: ResumeAdvisor,
        renderer: Renderer | None = None,
        user_model_store=None,  # UserModelStore（画像注入 + 持久化）
        user_id: str = "u_001",
        streaming: bool = False,  # agent 输出已流式打出, 不重复完整打印
        thread_id: str = "m1",  # 情景记忆/追踪元数据用（API 按会话传入，CLI 默认 m1）
    ) -> None:
        self.job_matcher = job_matcher
        self.resume_advisor = resume_advisor
        self.renderer = renderer or Renderer()
        self._user_model_store = user_model_store
        self._user_id = user_id
        self._thread_id = thread_id
        self._streaming = streaming  # 流式模式: agent 内容已逐 token 打出, 不再重复 show_agent
        self._messages: list = []  # 跨步骤对话历史

    def _profile_preamble(self) -> str | None:
        """从 UserModel 生成画像 preamble（有画像则不重复问）。"""
        if self._user_model_store is None:
            return None
        try:
            m = self._user_model_store.load(self._user_id)
        except Exception:
            return None
        parts: list[str] = []
        if m.profile.skills:
            parts.append(f"技能: {', '.join(m.profile.skills)}")
        if m.profile.direction:
            parts.append(f"方向: {m.profile.direction}")
        if m.profile.level:
            parts.append(f"级别: {m.profile.level}")
        if m.target_companies:
            parts.append(f"目标公司: {', '.join(m.target_companies)}")
        if m.preferences.city:
            parts.append(f"城市: {', '.join(m.preferences.city)}")
        if m.preferences.salary_min is not None:
            parts.append(f"薪资预期≥{m.preferences.salary_min}K")
        if not parts:
            return None
        # 标注为历史画像：与用户最新消息冲突时以最新消息为准（避免旧画像带偏方向）
        return "[用户画像]（历史存档；若与用户最新消息冲突，一律以用户最新消息为准）\n" + "\n".join(parts)

    def _sync_profile_from_intent(self, intent: str) -> None:
        """用户最新消息里的明确字段优先：提取并刷新画像，历史画像不再带偏方向/技能。"""
        if self._user_model_store is None:
            return
        llm = getattr(self.job_matcher, "llm", None)
        if llm is None:
            return
        from careercrew_core.agents.job_matcher import extract_profile_from_intent

        fields = extract_profile_from_intent(llm, intent)
        if not fields:
            return
        try:
            self._user_model_store.update(self._user_id, fields)
        except Exception:
            pass  # 刷新失败不阻塞匹配

    def _state(self, stage: str, text: str) -> dict:
        msgs = list(self._messages)
        preamble = self._profile_preamble()
        if preamble:
            msgs.append(SystemMessage(content=preamble))
        msgs.append(HumanMessage(content=text))
        return {
            "thread_id": self._thread_id, "user_id": self._user_id, "stage": stage, "user_intent": text,
            "messages": msgs, "pending_action": None, "agent_outputs": {}, "target_companies": [],
        }

    def run_match(self, intent: str) -> str:
        """阶段 match：JobMatcher 找匹配岗位，返回最终答案。"""
        self._sync_profile_from_intent(intent)  # 用户最新消息优先, 历史画像不再带偏方向
        state = self._state("match", intent)
        self.job_matcher.run(state)
        out = (self.job_matcher.last_result.content or "").strip()
        if not out:  # LLM 偶发空返回，兜底
            out = "（本轮未产出匹配结果，可补充技能/方向/城市后重试）"
        self._messages.append(HumanMessage(content=intent))
        self._messages.append(AIMessage(content=out, name="job_matcher"))
        return out

    def run_resume(self, jd_text: str) -> str:
        """阶段 resume：ResumeAdvisor 按 JD 定制简历（能看到此前对话/画像）。"""
        text = f"按这个 JD 定制简历：{jd_text}"
        state = self._state("resume", text)
        self.resume_advisor.run(state)
        out = (self.resume_advisor.last_result.content or "").strip()
        if not out:  # LLM 偶发空返回，兜底
            out = "（本轮未产出简历，可提供更多背景信息后重试）"
        self._messages.append(HumanMessage(content=text))
        self._messages.append(AIMessage(content=out, name="resume_advisor"))
        return out

    def run(
        self,
        intent: str,
        select_jd: Callable[[str], str | None] | None = None,
        user_id: str = "u_001",
    ) -> str:
        """M1 闭环：匹配 -> 选 JD -> 简历。select_jd 注入 JD 选择（测试 mock），默认交互。"""
        self._user_id = user_id
        self.renderer.banner()
        self.renderer.show_user(intent)
        self.renderer.show_status("匹配官正在检索岗位并评估匹配度...")
        if self._streaming:
            # 流式模式: 先打 agent 标签, 内容由 stream_callback 逐 token 打出, 结束收尾换行
            self.renderer.show_agent_label("job_matcher")
            match_out = self.run_match(intent)
            self.renderer.stream_end()
        else:
            match_out = self.run_match(intent)
            self.renderer.show_agent("job_matcher", match_out)

        jd = select_jd(match_out) if select_jd else self._prompt_jd()
        if not jd:
            return match_out

        self.renderer.show_status("简历顾问正在按所选 JD 定制简历...")
        if self._streaming:
            self.renderer.show_agent_label("resume_advisor")
            resume_out = self.run_resume(jd)
            self.renderer.stream_end()
        else:
            resume_out = self.run_resume(jd)
            self.renderer.show_agent("resume_advisor", resume_out)
        return resume_out

    def _prompt_jd(self) -> str | None:
        jd = self.renderer.prompt_choice("  输入要定制简历的目标 JD（回车跳过）: ").strip()
        return jd or None
