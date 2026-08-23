"""求职周期工作流（G2：意向 -> 匹配 -> 简历 部分闭环，M1 验收）。

编排：JobMatcher 找匹配岗位 -> 用户选目标 JD -> ResumeAdvisor 按 JD 定制简历。

UX 修复：
- 对话历史跨步骤携带（ResumeAdvisor 能看到 JobMatcher 环节用户提供的背景/简历，避免重复问）
- UserModel 画像注入（已有画像则不重复问）

（原 CLI 版的 Renderer 交互输出已随 CLI 移除，本模块由 careercrew_api.runtime 以 streaming 模式使用。）
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from careercrew_core.agents.job_matcher import JobMatcher
from careercrew_core.agents.resume_advisor import ResumeAdvisor


def _job_match_rows(result: Any) -> list[dict]:
    """从已成功执行的 memory_write 参数恢复候选岗位，供空正文兜底。"""
    rows: list[dict] = []
    for iteration in getattr(result, "iterations", None) or []:
        for call in getattr(iteration, "tool_calls", None) or []:
            if not isinstance(call, dict) or call.get("name") != "memory_write":
                continue
            args = call.get("args") or {}
            content = args.get("content") if args.get("type") == "job_match" else None
            if isinstance(content, dict) and content.get("title"):
                rows.append(content)
    return rows


def _render_recovered_match_report(result: Any) -> str:
    """模型正文为空时，从已经落库的候选岗位生成最小但真实的匹配报告。"""
    rows = _job_match_rows(result)
    if not rows:
        reason = getattr(result, "stopped_reason", "")
        if reason == "error":
            return "（职位检索过程出现异常，本轮报告生成失败，请稍后重试。）"
        searched = any(
            isinstance(call, dict) and call.get("name") == "search_jobs"
            for iteration in getattr(result, "iterations", None) or []
            for call in getattr(iteration, "tool_calls", None) or []
        )
        if searched:
            return "（平台检索已经完成，但匹配报告生成失败，请直接重试本轮。）"
        return "（尚未生成匹配报告，请补充目标岗位和城市后重试。）"

    lines = [
        "## 匹配报告",
        "",
        "| 检索方式 | 来源 | 公司 | 职位 | 城市 | 薪资 | 匹配度 | 匹配点 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        score = row.get("score")
        score_text = f"{float(score):.0%}" if isinstance(score, (int, float)) else "待评估"
        values = [
            row.get("retrieval_mode_label") or "检索方式未标注",
            row.get("source_label") or "来源未标注",
            row.get("company") or "公司名称未提供",
            row.get("title") or "职位名称未提供",
            row.get("city") or "未标注",
            row.get("salary") or "未标注",
            score_text,
            row.get("reason") or "已通过职位检索并加入候选池",
        ]
        escaped = [str(value).replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(escaped) + " |")
    lines.extend(("", "*报告由本轮已成功写入的候选岗位恢复。*"))
    return "\n".join(lines)


class JobCycle:
    def __init__(
        self,
        job_matcher: JobMatcher,
        resume_advisor: ResumeAdvisor,
        user_id: str,  # 必填：防止未来调用点漏传导致静默跨用户读写
        user_model_store=None,  # UserModelStore（画像注入 + 持久化）
        streaming: bool = False,  # agent 输出已流式打出, 不重复完整打印
        thread_id: str = "m1",  # 情景记忆/追踪元数据用（API 按会话传入，CLI 默认 m1）
        history_loader=None,  # 可选: Callable[[str, str], list]（user_id, thread_id）-> 历史消息
    ) -> None:
        self.job_matcher = job_matcher
        self.resume_advisor = resume_advisor
        self._user_model_store = user_model_store
        self._user_id = user_id
        self._thread_id = thread_id
        self._streaming = streaming  # 流式模式: agent 内容已逐 token 打出, 不再重复打印
        self._history_loader = history_loader
        self._messages: list = []  # 跨步骤对话历史
        self._selected_jd: str | None = None  # supervisor 图流转时由 match 节点写入

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

    def _state(self, stage: str, text: str) -> dict:
        # 有 history_loader 时历史由 BaseAgent 从 episodic 恢复，避免内存累积重复
        msgs = [] if self._history_loader else list(self._messages)
        preamble = self._profile_preamble()
        if preamble:
            msgs.append(SystemMessage(content=preamble))
        msgs.append(HumanMessage(content=text))
        return {
            "thread_id": self._thread_id, "user_id": self._user_id, "stage": stage, "user_intent": text,
            "messages": msgs, "pending_action": None, "agent_outputs": {}, "target_companies": [],
            # 本轮用户消息已先落库（record_user_message），历史恢复时跳过它避免重复
            "pending_user_entry_id": getattr(self, "pending_user_entry_id", None),
        }

    def run_match(self, intent: str, composed: str | None = None) -> str:
        """阶段 match：JobMatcher 找匹配岗位，返回最终答案。

        composed：可选的消息文本覆盖（附加上传文件/引用内容后的完整输入）；
        intent 仍用于画像抽取与记忆记录（保持展示层原话）。
        """
        # 画像更新由 JobMatcher 的 profile_update 工具负责；这里不再提前额外调用一次
        # LLM 做重复抽取，避免用户在看到任何岗位进度前先空等一轮模型响应。
        text = composed or intent
        state = self._state("match", text)
        self.job_matcher.run(state)
        out = (self.job_matcher.last_result.content or "").strip()
        if not out:  # LLM 偶发空返回：优先用已完成的工具结果恢复，不误报没岗位
            out = _render_recovered_match_report(self.job_matcher.last_result)
        self._messages.append(HumanMessage(content=text))
        self._messages.append(AIMessage(content=out, name="job_matcher"))
        return out

    def run_resume(self, jd_text: str, composed: str | None = None) -> str:
        """阶段 resume：ResumeAdvisor 按 JD 定制简历（能看到此前对话/画像）。"""
        text = composed or f"按这个 JD 定制简历：{jd_text}"
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
        user_id: str,
        select_jd: Callable[[str], str | None] | None = None,
    ) -> str:
        """M1 闭环（supervisor 图驱动）：匹配 -> 选 JD -> 简历。

        编排由 LangGraph supervisor 真实驱动：agent 节点执行完回 supervisor，
        按 state.stage 条件路由到下一个 agent 或 END（节点改 stage 推进流程，
        对齐 DEV_SPEC 3.1.1「agent 在执行中可改 stage 推进流程或终止」；
        "done" 不在 STAGE_AGENT_MAP 中，route 回退为 __end__）。
        select_jd 注入 JD 选择（测试 mock；生产 HITL interrupt 的前身），
        未选中 JD 则止步 match。
        """
        self._user_id = user_id

        from careercrew_core.supervisor.graph import build_graph

        def _matcher_node(state: dict) -> dict:
            out = self.run_match(intent)
            jd = select_jd(out) if select_jd else None
            self._selected_jd = jd
            return {
                "stage": "resume" if jd else "done",
                "agent_outputs": {"job_matcher": out},
            }

        def _resume_node(state: dict) -> dict:
            out = self.run_resume(self._selected_jd)
            return {"stage": "done", "agent_outputs": {"resume_advisor": out}}

        graph = build_graph({
            "job_matcher": _matcher_node,
            "resume_advisor": _resume_node,
        })
        final = graph.invoke(self._state("match", intent))

        outputs = final.get("agent_outputs") or {}
        return outputs.get("resume_advisor") or outputs.get("job_matcher") or ""
