"""Boss 消息页解析（E 批次：HR 回复监听的数据面）。

打开 Boss 聊天列表页，抽取会话（公司/职位/最后一条消息/未读数）。
解析与浏览器操作分离，单测用桩页面。
"""
from __future__ import annotations

from typing import Any

from careercrew_core.tools.browser.cdp import open_boss_page
from careercrew_core.tools.browser.patterns import BOSS_MESSAGE_PATTERNS
from careercrew_core.tools.browser.throttle import human_pause

# 会话列表项与字段（改版时只改这里）
CONV_ITEM = ".session-list li.item-item, .chat-conversation-list li"
CONV_FIELDS = {
    "company": ".item-text .name-text, .firm-name",
    "title": ".item-text .position-name, .job-name",
    "last_message": ".item-text .text-content, .msg-text",
    "unread": ".item-badge, .badge",
}


def _txt(el: Any, selector: str) -> str:
    node = el.query_selector(selector)
    if node is None:
        return ""
    try:
        return (node.inner_text() or "").strip()
    except Exception:
        return ""


def parse_conversations(items: list[Any]) -> list[dict]:
    """会话元素列表 -> [{company, title, last_message, unread}]。unread>0 才是 HR 新回复。"""
    out: list[dict] = []
    for it in items:
        company = _txt(it, CONV_FIELDS["company"])
        raw_unread = _txt(it, CONV_FIELDS["unread"])
        try:
            unread = int("".join(ch for ch in raw_unread if ch.isdigit()) or "0")
        except ValueError:
            unread = 0
        out.append({
            "company": company,
            "title": _txt(it, CONV_FIELDS["title"]),
            "last_message": _txt(it, CONV_FIELDS["last_message"]),
            "unread": unread,
        })
    return [c for c in out if c["company"]]


def fetch_new_replies(cdp_url: str) -> list[dict]:
    """拉取当前有未读的会话（即 HR 侧新消息）；渠道不可用抛异常由调度层吞掉记日志。"""
    with open_boss_page(cdp_url) as page:
        page.goto(BOSS_MESSAGE_PATTERNS["message_url"], timeout=30000,
                  wait_until="domcontentloaded")
        human_pause()
        page.wait_for_selector(CONV_ITEM, timeout=15000)
        items = page.query_selector_all(CONV_ITEM)
        convs = parse_conversations(list(items))
        return [c for c in convs if c["unread"] > 0]
