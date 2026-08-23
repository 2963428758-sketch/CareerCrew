"""E 批次：HR 回复监听的解析、多用户归属路由与去重单元测试（桩页面 + 桩记忆）。"""
from __future__ import annotations

from careercrew_api.hr_monitor import (
    _owned_replies,
    _user_application_map,
    record_hr_replies,
    run_monitor_cycle,
    start_hr_monitor,
)
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry
from careercrew_core.tools.browser.boss_messages import parse_conversations


class FakeEl:
    def __init__(self, texts: dict[str, str]):
        self._texts = texts

    def query_selector(self, sel: str):
        for s in sel.split(","):          # 组合选择器任一命中
            if s.strip() in self._texts:
                return FakeLeaf(self._texts[s.strip()])
        return None

    def query_selector_all(self, sel: str):
        return [self.query_selector(sel)] if self.query_selector(sel) else []


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
                ".item-text .text-content": "已收到，谢谢"}),
    ]
    convs = parse_conversations(items)
    assert convs[0]["company"] == "字节跳动" and convs[0]["unread"] == 2
    assert all(c["unread"] == 0 for c in convs[1:])


def _em(db: FakeMemoryDb, uid: str) -> EpisodicMemory:
    # thread_id=None：与生产一致，跨线程读写
    return EpisodicMemory(db, user_id=uid, thread_id=None)


def test_user_application_map_cross_thread() -> None:
    db = FakeMemoryDb()
    # 投递发生在不同聊天线程（生产语义），读取需跨线程可见
    EpisodicMemory(db, user_id="u1", thread_id="chat-a").write(
        MemoryEntry(type="application", content={"company": " 字节跳动 ", "title": "后端开发"}))
    EpisodicMemory(db, user_id="u1", thread_id="chat-b").write(
        MemoryEntry(type="application", content={"company": "腾讯", "title": ""}))
    m = _user_application_map(_em(db, "u1"))
    assert m == {"字节跳动": {"后端开发"}, "腾讯": {""}}
    assert _user_application_map(_em(db, "u2")) == {}


def test_owned_replies_company_and_title_matching() -> None:
    app_map = {"字节跳动": {"大模型应用工程师"}, "腾讯": {""}}   # 腾讯投递未填职位=不限职位
    replies = [
        {"company": "字节跳动", "title": "大模型应用工程师", "last_message": "hi"},   # 精确命中
        {"company": " 字节跳动  ", "title": "", "last_message": "x"},                # 归一后命中
        {"company": "字节跳动", "title": "前端开发", "last_message": "y"},           # 职位不符
        {"company": "腾讯", "title": "任意职位都算", "last_message": "z"},           # 空职位=不限
        {"company": "网易", "title": "游戏", "last_message": "w"},                   # 未投递
    ]
    owned = _owned_replies(replies, app_map)
    assert [r["last_message"] for r in owned] == ["hi", "x", "z"]


def test_record_hr_replies_dedupes_across_polling_cycles() -> None:
    db = FakeMemoryDb()
    replies = [{"company": "字节跳动", "title": "后端", "last_message": "明天面试？"}]
    n1 = record_hr_replies(lambda: _em(db, "u1"), replies)
    n2 = record_hr_replies(lambda: _em(db, "u1"), replies)      # 同一轮询下轮重复拉到
    assert (n1, n2) == (1, 0)
    assert len(_em(db, "u1").list(type="hr_reply")) == 1


class _Acc:
    """双账号假存储。"""

    @staticmethod
    def list_accounts(offset, limit):
        return ({"id": "u1"}, {"id": "u2"}), 2


class _Search:
    boss_cdp_url = "http://127.0.0.1:9222"


class _Tools:
    search = _Search()


class _Settings:
    tools = _Tools()


class _Rt:
    settings = _Settings()


def _seed_application(db: FakeMemoryDb, uid: str, company: str, title: str = "") -> None:
    _em(db, uid).write(MemoryEntry(type="application",
                                   content={"company": company, "title": title}))


def test_run_monitor_cycle_routes_replies_to_owning_users() -> None:
    db = FakeMemoryDb()
    _seed_application(db, "u1", "字节跳动")
    _seed_application(db, "u2", "腾讯")
    replies = [
        {"company": "字节跳动", "title": "后端", "last_message": "字节回复"},
        {"company": "腾讯", "title": "后端", "last_message": "腾讯回复"},
        {"company": "网易", "title": "游戏", "last_message": "未投递公司"},
    ]
    stats = run_monitor_cycle(_Rt(), type("A", (), {"store": _Acc})(), fetch=lambda url: replies,
                              memory_db=db)
    assert stats["checked"] == 3 and stats["matched"] == 2
    u1_msgs = _em(db, "u1").list(type="hr_reply")
    u2_msgs = _em(db, "u2").list(type="hr_reply")
    assert [m.content["company"] for m in u1_msgs] == ["字节跳动"]
    assert [m.content["company"] for m in u2_msgs] == ["腾讯"]


def test_run_monitor_cycle_skips_users_without_applications() -> None:
    db = FakeMemoryDb()          # 没有任何投递记录
    stats = run_monitor_cycle(_Rt(), type("A", (), {"store": _Acc})(),
                              fetch=lambda url: [{"company": "任意", "unread": 1}],
                              memory_db=db)
    assert stats["written"] == 0 and stats["matched"] == 0


def test_run_monitor_cycle_fetch_failure_swallowed(monkeypatch) -> None:
    def boom(url):
        raise RuntimeError("风控页")

    stats = run_monitor_cycle(_Rt(), type("A", (), {"store": _Acc})(), fetch=boom,
                              memory_db=FakeMemoryDb())
    assert stats == {"checked": 0, "written": 0, "matched": 0}   # 失败不抛出，下轮重试


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
