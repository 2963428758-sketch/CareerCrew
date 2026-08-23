"""HR 回复监听调度（E 批次）：定时拉取 Boss 未读会话，写入情景记忆树。

投递后的完整闭环：send_greeting 发出招呼（N2）-> HR 回复被本模块捕获 ->
hr_reply 事件入情景记忆 -> SalaryNegotiator / Interviewer 后续对话可引用。

多用户归属（v2）：回复只写给「投递过该公司」的账号——归属依据是 N2 落库的
application 情景事件（公司归一匹配，职位双向包含辅助消歧）；未匹配到任何
投递记录的回复跳过并计数（可能是用户在 Boss 上手动发起的会话）。
去重：同一 (company, message) 已入过该用户记忆则跳过，轮询周期间不重复写。

配置 `hr_monitor.enabled`（默认 false）+ `interval_minutes`；
CDP 地址默认复用 tools.search.boss_cdp_url。全部失败仅记日志。
"""
from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger("careercrew_api.hr_monitor")


def _norm(s: str) -> str:
    """公司/职位/消息归一：压空白 + 小写，消除大小写与排版差异。"""
    return " ".join((s or "").split()).lower()


def _user_application_map(episodic) -> dict[str, set[str]]:
    """该用户投递过的公司 -> 职位集合（跨线程读 application 事件）。"""
    out: dict[str, set[str]] = {}
    try:
        entries = episodic.list(type="application", limit=500)
    except Exception:
        return out
    for e in entries:
        c = e.content if isinstance(e.content, dict) else {}
        company = _norm(str(c.get("company") or ""))
        if not company:
            continue
        out.setdefault(company, set()).add(_norm(str(c.get("title") or "")))
    return out


def _owned_replies(replies: list[dict], app_map: dict[str, set[str]]) -> list[dict]:
    """筛出归属于该用户的回复：公司命中；双方职位均非空时需双向包含
    （投递记录职位为空 = 不限职位，任何该公司的回复都归属）。"""
    owned: list[dict] = []
    for r in replies:
        titles = app_map.get(_norm(r.get("company") or ""))
        if not titles:
            continue
        title = _norm(r.get("title") or "")
        if title and not any((not t) or (t in title or title in t) for t in titles):
            continue
        owned.append(r)
    return owned


def record_hr_replies(episodic_factory: Callable[[], object], replies: list[dict], *,
                      memory_service=None, user_id: str | None = None) -> int:
    """把回复写入该用户情景记忆；(company,message) 已存在则去重跳过。返回新写条数。"""
    from careercrew_core.memory.types import MemoryEntry

    em = episodic_factory()
    seen: set[tuple[str, str]] = set()
    try:
        for e in em.list(type="hr_reply", limit=1000):
            c = e.content if isinstance(e.content, dict) else {}
            seen.add((_norm(str(c.get("company") or "")), _norm(str(c.get("message") or ""))))
    except Exception:
        logger.warning("hr_reply 去重索引读取失败，本轮可能重复写入", exc_info=True)

    written = 0
    for r in replies:
        company = str(r.get("company") or "")
        message = str(r.get("last_message") or "")[:300]
        key = (_norm(company), _norm(message))
        if key in seen:
            continue
        try:
            content = {
                "company": company,
                "title": r.get("title", ""),
                "message": message,
            }
            if memory_service is not None:
                memory_service.write_event(
                    user_id or em.user_id, "hr_reply", content, thread_id=em.thread_id,
                )
            else:
                em.write(MemoryEntry(type="hr_reply", content=content))
            seen.add(key)
            written += 1
        except Exception:
            logger.warning("hr_reply 写入失败 company=%s", company, exc_info=True)
    return written


def run_monitor_cycle(rt, auth_service, fetch, memory_db=None) -> dict:
    """对所有账号跑一轮：拉未读 -> 按 application 归属路由 -> 写记忆（去重）。"""
    cdp_url = ""
    try:
        cdp_url = rt.settings.tools.search.boss_cdp_url or ""
    except Exception:
        pass
    if not cdp_url.strip():
        return {"checked": 0, "written": 0, "matched": 0}

    try:
        accounts, _total = auth_service.store.list_accounts(0, 10_000)
    except Exception:
        logger.exception("hr_monitor: 枚举账号失败，本轮跳过")
        return {"checked": 0, "written": 0, "matched": 0}

    try:
        replies = fetch(cdp_url)
    except Exception as e:
        logger.warning("hr_monitor: 拉取失败（%s: %s），下轮重试", type(e).__name__, e)
        return {"checked": 0, "written": 0, "matched": 0}
    checked = len(replies)
    if not replies:
        return {"checked": 0, "written": 0, "matched": 0}

    from careercrew_core.memory import create_memory_db
    from careercrew_core.memory.episodic import EpisodicMemory

    db = memory_db if memory_db is not None else create_memory_db(rt.settings)
    memory_service = getattr(rt, "memory_service", None)

    written = matched = 0
    for acc in accounts:
        uid = acc.get("id")
        if not uid:
            continue
        try:
            # 后台轮询属于自动记忆生成：策略关闭时不读写任何长期记忆。
            if memory_service is not None and not memory_service.effective_policy(uid).can_generate:
                continue
            # thread_id=None：跨线程读该用户全部 application/hr_reply 事件
            em = EpisodicMemory(db, user_id=uid, thread_id=None)
            app_map = _user_application_map(em)
            if not app_map:
                continue  # 该用户没有经 CareerCrew 的投递记录，不接收任何回复
            owned = _owned_replies(replies, app_map)
            if not owned:
                continue
            matched += len(owned)
            written += record_hr_replies(
                lambda em=em: em, owned, memory_service=memory_service, user_id=uid,
            )
        except Exception:
            logger.exception("hr_monitor: 处理失败 user=%s", uid)

    if matched < checked:
        logger.info(
            "hr_monitor: %d/%d 条回复匹配到投递记录（未匹配的多为站外手动会话，已跳过）",
            matched, checked,
        )
    if written:
        logger.info("hr_monitor: 本轮新写入 %d 条 HR 回复", written)
    return {"checked": checked, "written": written, "matched": matched}


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
