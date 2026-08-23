"""E 批次：HR 回复监听的解析与调度周期单元测试（桩页面 + 桩记忆）。"""
from __future__ import annotations

from careercrew_api.hr_monitor import record_hr_replies, run_monitor_cycle, start_hr_monitor
from careercrew_core.tools.browser.boss_messages import parse_conversations


class FakeEl:
    def __init__(self, texts: dict[str, str]):
        self._texts = texts
        self._tags = set(texts)

    def query_selector(self, sel: str):
        for s in sel.split(","):          # 组合选择器任一命中
            if s.strip() in self._texts:
                return FakeLeaf(self._texts[s.strip()])
        return None

    def query_selector_all(self, sel: str):
        return [self.query_selector(sel)] if sel in self._texts else []


class FakeLeaf:
    def __init__(self, text: str):
        self._t = text

    def inner_text(self):
        return self._t


def test_parse_conversations_unread_only_filtering() -> None:
    items = [
        FakeEl({".item-text .name-text": "字节跳动", ".item-text .position-name": "大模型应用",
                ".item-text .text-content": "方便看下明天的时间吗？", ".item-badge": "2"}),
        FakeEl({".item-text .name-text": "腾讯", ".item-text .position-name": "后端开发",
                ".item-text .text-content": "已收到，谢谢", "" : ""}),  # 无未读徽标
    ]
    convs = parse_conversations(items)
    assert convs[0]["company"] == "字节跳动" and convs[0]["unread"] == 2
    assert all(c["unread"] == 0 for c in convs[1:])


def test_record_hr_replies_writes_memory_entries() -> None:
    from careercrew_core.memory.db import FakeMemoryDb
    from careercrew_core.memory.episodic import EpisodicMemory

    db = FakeMemoryDb()
    n = record_hr_replies(
        lambda: EpisodicMemory(db, user_id="u1", thread_id="t1"),
        [{"company": "字节跳动", "title": "大模型应用", "last_message": "明天 15:00 面试？"}],
    )
    assert n == 1
    entries = EpisodicMemory(db, user_id="u1", thread_id="t1").list(type="hr_reply")
    assert entries[0].content["company"] == "字节跳动"
    assert "面试" in entries[0].content["message"]


class _Acc:
    """记录构造参数的假账号存储。"""

    @staticmethod
    def list_accounts(offset, limit):
        return ({"id": "u1"}, {"id": "u2"}), 2


def test_run_monitor_cycle_disabled_without_cdp() -> None:
    class Rt:
        class settings:
            class tools:
                class search:
                    boss_cdp_url = ""

    stats = run_monitor_cycle(Rt(), type("A", (), {"store": _Acc})(), fetch=lambda url: [])
    assert stats == {"checked": 0, "written": 0}


def test_run_monitor_cycle_fetch_failure_swallowed(monkeypatch) -> None:
    class Search:
        boss_cdp_url = "http://127.0.0.1:9222"

    class Tools:
        search = Search()

    class Settings:
        tools = Tools()

    class Rt:
        settings = Settings()

    def boom(url):
        raise RuntimeError("风控页")

    stats = run_monitor_cycle(Rt(), type("A", (), {"store": _Acc})(), fetch=boom)
    assert stats == {"checked": 0, "written": 0}     # 失败不抛出，下轮重试


def test_start_hr_monitor_noop_when_disabled() -> None:
    started = []

    class FakeThread:
        def __init__(self, **k):
            started.append(k)

        def start(self): ...

    import threading
    orig = threading.Thread
    threading.Thread = FakeThread
    try:
        start_hr_monitor(None, None, enabled=False, interval_minutes=30, stop=None)
    finally:
        threading.Thread = orig
    assert started == []      # 未启动任何线程
