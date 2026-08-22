"""Auto Dream 后台调度：每日低峰对活跃用户跑 consolidation（README 宣称的"定期合并"）。

配置 `memory.consolidation.dream_schedule`："off"（默认，行为不变）或 "HH:MM"（本地时区）。
门控（min_interval_hours / min_sessions）由 Consolidator.should_run 负责，未到即跳过；
本模块只负责"到点触发"。全部失败仅记日志，绝不影响主服务。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

logger = logging.getLogger("careercrew_api.dream")


def parse_schedule(schedule: str) -> tuple[int, int] | None:
    """解析 "HH:MM"；"off"/空/非法返回 None（不调度）。"""
    s = (schedule or "").strip()
    if not s or s.lower() == "off":
        return None
    parts = s.split(":")
    if len(parts) != 2:
        logger.warning("dream_schedule 非法: %r（应为 HH:MM 或 off），已忽略", schedule)
        return None
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        logger.warning("dream_schedule 非法: %r（应为 HH:MM 或 off），已忽略", schedule)
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        logger.warning("dream_schedule 越界: %r，已忽略", schedule)
        return None
    return hh, mm


def dream_due(now: datetime, hhmm: tuple[int, int], last_run_date: str) -> bool:
    """当前时刻是否该触发（当日已跑过则不再触发）。"""
    return now.strftime("%H:%M") >= f"{hhmm[0]:02d}:{hhmm[1]:02d}" and last_run_date != now.date().isoformat()


def run_dream_cycle(rt, auth_service, now: datetime | None = None) -> dict:
    """对所有账号各跑一次 consolidation（内部有 should_run 门控）。返回统计。"""
    now = now or datetime.now()
    ran = skipped = failed = 0
    try:
        accounts, _total = auth_service.store.list_accounts(0, 10_000)
    except Exception:
        logger.exception("dream: 枚举账号失败，本轮跳过")
        return {"ran": 0, "skipped": 0, "failed": 0, "error": "list_accounts"}
    for acc in accounts:
        uid = acc.get("id")
        if not uid:
            continue
        try:
            result = rt.memory_consolidate(uid)
            if result.get("ran"):
                ran += 1
            else:
                skipped += 1
        except Exception:
            failed += 1
            logger.exception("dream: consolidation 失败 user=%s", uid)
    if ran or failed:
        logger.info("dream cycle: ran=%d skipped=%d failed=%d", ran, skipped, failed)
    return {"ran": ran, "skipped": skipped, "failed": failed}


def start_dream_scheduler(
    get_runtime: Callable[[], object],
    get_auth_service: Callable[[], object],
    schedule: str,
    stop,
) -> None:
    """启动守护线程；schedule="off" 时为 no-op。每分钟检查一次是否到点。"""
    hhmm = parse_schedule(schedule)
    if hhmm is None:
        return
    import threading

    def _loop() -> None:
        last_run_date = ""
        while not stop.wait(60):
            try:
                if dream_due(datetime.now(), hhmm, last_run_date):
                    rt = get_runtime()
                    rt._ensure_heavy() if hasattr(rt, "_ensure_heavy") else None
                    run_dream_cycle(rt, get_auth_service())
                    last_run_date = datetime.now().date().isoformat()
            except Exception:
                logger.exception("dream scheduler tick failed")

    threading.Thread(target=_loop, name="dream-consolidation", daemon=True).start()
