"""CDP 接管通道（N1）：patchright connect_over_cdp 接管用户已登录的 Chrome。

使用前提：用户 Chrome 以 --remote-debugging-port=9222 启动并已登录目标站点。
设计要点：
- patchright（playwright 反检测分支）+ connect_over_cdp：不注入 webdriver 痕迹，
  复用用户真实登录态，无需账号密码；
- 每次采集新建连接、用毕断开——playwright sync 对象绑定创建线程，
  工具运行在线程池中跨线程复用会崩；连接开销（~几百 ms）相对采集耗时可忽略；
- browser.close() 对 CDP 连接只断开不关闭用户浏览器。
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any


@contextlib.contextmanager
def open_cdp_page(cdp_url: str, timeout_ms: int = 20000) -> Iterator[Any]:
    """连上 CDP 浏览器并开一个新页面；退出时关页面、断连接（浏览器进程不受影响）。"""
    if not (cdp_url or "").strip():
        raise ValueError("CDP 调试端口未配置（tools.search.boss_cdp_url），渠道禁用")

    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url, timeout=timeout_ms)
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            try:
                yield page
            finally:
                with contextlib.suppress(Exception):
                    page.close()
        finally:
            with contextlib.suppress(Exception):
                browser.close()


# 向后兼容别名
open_boss_page = open_cdp_page

