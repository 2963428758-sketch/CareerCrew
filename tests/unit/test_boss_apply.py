"""N2 真实投递工具单元测试：Fake 页面驱动 发送->验证->留痕 全流程。

HITL 拦截语义已在 tests/unit/test_hitl_middleware.py 覆盖，此处测确认后的执行路径。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.tools.browser.boss_apply import (
    generate_greeting,
    make_send_greeting_tool,
    record_apply_attempt,
)
from tests.fakes import FakeChatModel


class FakeLocator:
    """playwright Locator 协议桩：count/first/click/fill/input_value。"""

    def __init__(self, page: FakePage, selector: str):
        self._page = page
        self._selector = selector

    @property
    def first(self) -> FakeLocator:
        return self

    def count(self) -> int:
        # 组合选择器（"a, b, c"）任一命中即视为存在
        return int(any(s.strip() in self._page.present for s in self._selector.split(",")))

    def click(self) -> None:
        self._page.actions.append(("click", self._selector))

    def fill(self, text: str) -> None:
        self._page.input_buffer = text
        self._page.actions.append(("fill", text))

    def input_value(self) -> str:
        return self._page.input_after_send


class FakePage:
    def __init__(self, chat_btn=True, input_box=True):
        self.present = {".btn-startchat", "#chat-input", ".btn-send"} - (
            set() if chat_btn else {".btn-startchat"}
        ) - (set() if input_box else {"#chat-input"})
        self.actions: list[tuple] = []
        self.gotos: list[str] = []
        self.input_buffer = ""
        # 发送后 Boss 清空输入框 -> 默认模拟发送成功；置非空则模拟失败
        self.input_after_send = ""

    def goto(self, url, timeout=None, wait_until=None):
        self.gotos.append(url)

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)


class FakeCDP:
    """open_boss_page 的上下文桩。"""

    def __init__(self, page: FakePage):
        self.page = page

    def __enter__(self):
        return self.page

    def __exit__(self, *exc):
        return False


@pytest.fixture
def em() -> EpisodicMemory:
    return EpisodicMemory(FakeMemoryDb(), user_id="u1", thread_id="t-apply")


def _make_tool(monkeypatch, page: FakePage, em: EpisodicMemory):
    import careercrew_core.tools.browser.boss_apply as mod

    monkeypatch.setattr(mod, "open_boss_page", lambda cdp_url, timeout_ms=20000: FakeCDP(page))
    return make_send_greeting_tool(cdp_url="http://127.0.0.1:9222",
                                   episodic_factory=lambda: em)


def test_send_greeting_success_flow_and_record(monkeypatch, em) -> None:
    page = FakePage()
    tool = _make_tool(monkeypatch, page, em)
    out = tool.invoke({
        "job_url": "https://www.zhipin.com/job_card/abc.html",
        "message": "3 年 RAG/Agent 经验，与贵司岗位高度匹配，期待沟通。",
        "company": "字节跳动", "title": "大模型应用工程师",
    })
    assert "已发送" in out
    assert page.actions[0][0] == "click" and ".btn-startchat" in page.actions[0][1]
    assert page.actions[1] == ("fill", "3 年 RAG/Agent 经验，与贵司岗位高度匹配，期待沟通。")
    entries = em.list(type="application")
    assert len(entries) == 1 and entries[0].content["status"] == "sent"
    assert entries[0].content["company"] == "字节跳动"


def test_send_greeting_missing_chat_btn_records_failure_and_retryable(
    monkeypatch, em,
) -> None:
    page = FakePage(chat_btn=False)
    tool = _make_tool(monkeypatch, page, em)
    out = tool.invoke({"job_url": "https://www.zhipin.com/job_card/x.html",
                       "message": "hi", "company": "腾讯", "title": "后端"})
    assert "发送失败" in out and "重试" in out
    entries = em.list(type="application")
    assert entries[0].content["status"] == "failed"
    assert "立即沟通" in entries[0].content["error"]


def test_send_greeting_send_not_verified_marks_failed(monkeypatch, em) -> None:
    page = FakePage()
    page.input_after_send = "未清空"          # 发送后输入框仍有内容 -> 判定失败
    tool = _make_tool(monkeypatch, page, em)
    out = tool.invoke({"job_url": "u", "message": "m"})
    assert "发送失败" in out
    assert em.list(type="application")[0].content["status"] == "failed"


def test_generate_greeting_truncated_and_clean() -> None:
    llm = FakeChatModel([AIMessage(content="您好，我有 3 年 RAG 与 LangGraph 多智能体经验，匹配贵司 JD，期待聊聊！")])
    out = generate_greeting("JD：大模型应用…", "简历亮点：RAG/Agent", llm)
    assert "RAG" in out and len(out) <= 300


def test_record_apply_attempt_survives_store_errors() -> None:
    class BoomStore:
        def write(self, entry): raise RuntimeError("db down")

    record_apply_attempt(BoomStore(), "C", "T", "sent")   # 不抛出即通过
