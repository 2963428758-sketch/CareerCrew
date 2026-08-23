"""HR 回复监听调度（E 批次）：定时拉取 Boss 未读会话，写入情景记忆树。

投递后的完整闭环：send_greeting 发出招呼（N2）-> HR 回复被本模块捕获 ->
hr_reply 事件入情景记忆 -> SalaryNegotiator / Interviewer 后续对话可引用。

配置 `hr_monitor.enabled`（默认 false，行为不变）+ `interval_minutes`；
CDP 地址默认复用 tools.search.boss_cdp_url。全部失败仅记日志。
"""
from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger("careercrew_api.hr_monitor")


def record_hr_replies(episodic_factory: Callable[[], object], replies: list[dict]) -> int:
    """把未读会话写为情景记忆事件；返回写入条数。"""
    from careercrew_core.memory.types import MemoryEntry

    written = 0
    for r in replies:
        try:
            episodic_factory().write(MemoryEntry(type="hr_reply", content={
                "company": r.get("company", ""),
                "title": r.get("title", ""),
                "message": (r.get("last_message") or "")[:300],
            }))
            written += 1
        except Exception:
            logger.warning("hr_reply 写入失败 company=%s", r.get("company"), exc_info=True)
    return written


def run_monitor_cycle(rt, auth_service, fetch) -> dict:
    """对所有账号跑一轮：拉未读 -> 写记忆。fetch(cdp_url)->replies 可注入测试桩。"""
    cdp_url = ""
    try:
        cdp_url = rt.settings.tools.search.boss_cdp_url or ""
    except Exception:
        pass
    if not cdp_url.strip():
        return {"checked": 0, "written": 0}

    try:
        accounts, _total = auth_service.store.list_accounts(0, 10_000)
    except Exception:
        logger.exception("hr_monitor: 枚举账号失败，本轮跳过")
        return {"checked": 0, "written": 0}

    checked = written = 0
    try:
        replies = fetch(cdp_url)
    except Exception as e:
        logger.warning("hr_monitor: 拉取失败（%s: %s），下轮重试", type(e).__name__, e)
        return {"checked": 0, "written": 0}
    checked = len(replies)

    from careercrew_core.memory import create_memory_db
    from careercrew_core.memory.episodic import EpisodicMemory

    memory_db = create_memory_db(rt.settings)

    def _factory(user_id: str):
        # Boss 会话与账号的映射 MVP 阶段不区分（单用户部署为主），
        # 多用户时按会话归属过滤——见 N 批次遗留说明。
        return EpisodicMemory(memory_db, user_id=user_id)

    for acc in accounts:
        uid = acc.get("id")
        if not uid:
            continue
        try:
            written += record_hr_replies(lambda u=uid: _factory(u), replies)
        except Exception:
            logger.exception("hr_monitor: 写入失败 user=%s", uid)
    if written:
        logger.info("hr_monitor: %d 条 HR 回复已入情景记忆", written)
    return {"checked": checked, "written": written}


def start_hr_monitor(get_runtime: Callable[[], object], get_auth_service: Callable[[], object],
                     enabled: bool, interval_minutes: int, stop) -> None:
    """守护线程：每 interval 分钟一轮；enabled=False 时 no-op。"""
    if not enabled:
        return
    import threading

    interval = max(int(interval_minutes), 1) * 60

    def _loop() -> None:
        from careercrew_core.tools.browser.boss_messages import fetch_new_replies

        while not stop.wait(interval):
            try:
                run_monitor_cycle(get_runtime(), get_auth_service(), fetch_new_replies)
            except Exception:
                logger.exception("hr_monitor tick failed")

    threading.Thread(target=_loop, name="hr-reply-monitor", daemon=True).start()
