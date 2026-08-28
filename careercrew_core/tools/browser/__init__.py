"""浏览器自动化通道（N1/N2）：CDP 接管 + site-patterns + 高斯节流。

仅当用户显式配置 CDP 调试端口时启用；所有站点选择器集中在 patterns.py。
"""
from careercrew_core.tools.browser.boss_search import parse_job_cards, search_boss_jobs
from careercrew_core.tools.browser.cdp import open_boss_page, open_cdp_page
from careercrew_core.tools.browser.liepin_search import (
    parse_liepin_job_cards,
    search_liepin_jobs,
)
from careercrew_core.tools.browser.throttle import gauss_delay_ms, human_pause

__all__ = [
    "gauss_delay_ms",
    "human_pause",
    "open_boss_page",
    "open_cdp_page",
    "parse_job_cards",
    "parse_liepin_job_cards",
    "search_boss_jobs",
    "search_liepin_jobs",
]

