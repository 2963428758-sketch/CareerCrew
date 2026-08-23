"""Boss直聘搜索后端（N1）：CDP 接管已登录 Chrome 抓取岗位列表。

解析与浏览器操作分离：parse_job_cards 只吃 ElementHandle 协议对象
（真实 handle / 测试桩均可），单测无需真浏览器。
输出 dict 与 JobsStore.upsert 对齐（source="boss"），url 留给详情页跳转。
"""
from __future__ import annotations

import logging
from typing import Any

from careercrew_core.tools.browser.cdp import open_boss_page
from careercrew_core.tools.browser.patterns import BOSS_PATTERNS
from careercrew_core.tools.browser.throttle import human_pause

logger = logging.getLogger(__name__)


def _text(card: Any, selector: str) -> str:
    """取卡片内字段文本；选择器未命中返回空串（改版容错）。"""
    el = card.query_selector(selector)
    if el is None:
        return ""
    try:
        return (el.inner_text() or "").strip()
    except Exception:
        return ""


def parse_job_cards(cards: list[Any]) -> list[dict]:
    """把岗位卡片元素列表解析为 JobsStore 行。"""
    f = BOSS_PATTERNS["fields"]
    jobs: list[dict] = []
    for card in cards:
        title = _text(card, f["title"])
        link_el = card.query_selector(f["link"])
        url = (link_el.get_attribute("href") or "").strip() if link_el else ""
        # 相对路径补全
        if url.startswith("/"):
            url = f"https://www.zhipin.com{url}"
        exp_parts = [t.strip() for t in _all_texts(card, f["experience"]) if t.strip()]
        jobs.append({
            "title": title,
            "company": _text(card, f["company"]),
            "city": _text(card, f["area"]),
            "salary": _text(card, f["salary"]),
            "experience": " | ".join(exp_parts),
            "jd": "",                      # 列表页无 JD 正文；详情按需再抓（MVP 不做）
            "url": url,
            "source": "boss",
        })
    return [j for j in jobs if j["title"]]  # 无标题的脏卡片丢弃


def _all_texts(card: Any, selector: str) -> list[str]:
    out = []
    for el in card.query_selector_all(selector):
        try:
            out.append((el.inner_text() or "").strip())
        except Exception:
            continue
    return out


def _looks_blocked(page: Any) -> bool:
    """风控验证页探测：命中特征即放弃本渠道（上层降级猎聘 MCP）。"""
    for marker in BOSS_PATTERNS["block_markers"]:
        try:
            if marker.startswith("text="):
                if page.locator(marker).count() > 0:
                    return True
            elif page.query_selector(marker) is not None:
                return True
        except Exception:
            continue
    return False


def search_boss_jobs(
    direction: str, top_k: int = 8, cdp_url: str = "", city: str = "",
    pause: bool = True,
) -> list[dict]:
    """Boss直聘搜索岗位；渠道不可用（未配置/风控页/超时）抛异常由上层降级。"""
    with open_boss_page(cdp_url) as page:
        url = BOSS_PATTERNS["search_url"].format(
            query=direction.strip(), city=(city or "").strip()
        )
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        if pause:
            human_pause()
        page.wait_for_selector(BOSS_PATTERNS["wait_selector"], timeout=15000)

        if _looks_blocked(page):
            raise RuntimeError("Boss直聘命中安全验证，请手动通过验证后重试")

        cards = page.query_selector_all(BOSS_PATTERNS["job_card"])
        jobs = parse_job_cards(list(cards)[:top_k])
        logger.info("boss search %r -> %d jobs", direction, len(jobs))
        return jobs
