"""Boss直聘真实投递（N2）：招呼语发送 + 结果验证 + 尝试留痕。

链路：agent 按 JD+简历生成 message -> HITL 确认闸门（既有）->
本模块打开岗位详情页点「立即沟通」-> 填入招呼语 -> 发送 -> 验证气泡 ->
写 apply_attempt 情景事件（sent/failed，failed 可重试）。

与 mock_apply 的关系：CDP 未配置时上层注册的仍是 mock 版（行为不变）；
配置 tools.search.boss_cdp_url 后 make_send_greeting_tool 切换为真实通道。
"""
from __future__ import annotations

import logging
from typing import Any

from careercrew_core.tools.browser.cdp import open_boss_page
from careercrew_core.tools.browser.patterns import BOSS_MESSAGE_PATTERNS
from careercrew_core.tools.browser.throttle import human_pause

logger = logging.getLogger(__name__)

# 岗位详情页「立即沟通」按钮（弹窗聊天框与消息页共用输入框选择器）
_DETAIL_CHAT_BTN = ".btn-startchat, .op-btn-chat, :text('立即沟通')"


def record_apply_attempt(episodic: Any, company: str, title: str,
                         status: str, detail: dict | None = None) -> None:
    """把一次投递尝试写入情景记忆树（type=application），失败可检索后重试。"""
    from careercrew_core.memory.types import MemoryEntry

    content = {"company": company, "title": title, "status": status, **(detail or {})}
    try:
        episodic.write(MemoryEntry(type="application", content=content))
        logger.info("apply attempt recorded: %s %s -> %s", company, title, status)
    except Exception:
        # 留痕失败不阻断投递主流程
        logger.warning("apply attempt record failed", exc_info=True)


def send_greeting_real(job_url: str, message: str, cdp_url: str) -> str:
    """打开 Boss 岗位详情页发起沟通并发送招呼语；返回人类可读结果。

    Raises:
        RuntimeError: 未配置 CDP / 页面元素缺失 / 发送后未验证到气泡。
    """
    if not (job_url or "").strip():
        raise ValueError("job_url 为空：send_greeting 需要 search_jobs 返回的岗位链接")
    with open_boss_page(cdp_url) as page:
        page.goto(job_url, timeout=30000, wait_until="domcontentloaded")
        human_pause()

        btn = page.locator(_DETAIL_CHAT_BTN).first
        if btn.count() == 0:
            raise RuntimeError("详情页未找到「立即沟通」入口（可能已沟通过或页面改版）")
        btn.click()
        human_pause()

        box = page.locator(BOSS_MESSAGE_PATTERNS["send_box"])
        if box.count() == 0:
            raise RuntimeError("聊天输入框未出现（可能命中风控验证）")
        box.fill(message)
        page.locator(BOSS_MESSAGE_PATTERNS["send_btn"]).first.click()
        human_pause()

        # 验证：输入框被清空视为已发出（Boss 发送后清空输入框）
        remaining = (box.input_value() or "").strip()
        if remaining:
            raise RuntimeError("发送后输入框仍有内容，判定发送失败")

        return f"招呼语已发送至 {job_url}"


def make_send_greeting_tool(cdp_url: str = "", episodic_factory=None):
    """构造真实 send_greeting 工具（N2）。episodic_factory() 返回情景记忆实例用于留痕。"""

    from langchain_core.tools import tool

    @tool
    def send_greeting(job_url: str, message: str, company: str = "", title: str = "") -> str:
        """向岗位 HR 发送投递招呼语（高风险动作，需用户确认后才会执行）。

        Args:
            job_url: search_jobs 返回的 Boss 岗位链接。
            message: 按 JD+简历定制的招呼语（建议 120 字内，突出匹配点）。
            company: 公司名（仅用于留痕）。
            title: 职位名（仅用于留痕）。
        """
        try:
            result = send_greeting_real(job_url, message, cdp_url=cdp_url)
            if episodic_factory is not None:
                record_apply_attempt(episodic_factory(), company or "?", title or "?",
                                     "sent", {"message": message[:200], "job_url": job_url})
            return result
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            if episodic_factory is not None:
                try:
                    record_apply_attempt(episodic_factory(), company or "?", title or "?",
                                         "failed", {"error": err, "job_url": job_url})
                except Exception:
                    pass
            return f"发送失败（{err}）。该尝试已记录，修正后可直接重试。"

    return send_greeting


def generate_greeting(jd_text: str, resume_summary: str, llm: Any) -> str:
    """按 JD+简历生成 Boss 招呼语（120 字内，突出匹配点与可用性）。"""
    prompt = (
        "你是求职助手，为 Boss直聘生成一条打招呼语。\n"
        f"岗位 JD：\n{jd_text[:800]}\n\n候选人亮点：\n{resume_summary[:400]}\n\n"
        "要求：不超过 120 字；第一句点明最硬的匹配点；结尾表达沟通意愿；"
        "不要套话不要表情符号。直接输出招呼语正文。"
    )
    resp = llm.invoke(prompt)
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    return content.strip()[:300]
