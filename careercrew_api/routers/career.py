"""求职持续跟进 API（第二/三期）：看板、素材库、行动任务、HR 跟进、Offer 对比、
真实面试复盘、面试复盘报告、可解释匹配、统计、全局搜索、画像与隐私控制。

与 /api/preparation 一样走独立 CareerStore 依赖，不依赖任何 LLM 运行时；
gap-analysis 与面试复盘报告在 runtime.llm 可用时做语义增强，否则规则兜底。
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.routers.preparation import get_preparation_store
from careercrew_core.career.models import (
    ActionItemInput,
    BoardStatusInput,
    CareerProfileInput,
    ContactInput,
    HRFollowupInput,
    HRReplyDraftInput,
    MaterialInput,
    OfferInput,
    RealInterviewInput,
)
from careercrew_core.career.product_events import safe_event
from careercrew_core.career.store import CareerStore
from careercrew_core.preparation.store import PreparationStore

router = APIRouter()


@lru_cache(maxsize=1)
def get_career_store() -> CareerStore:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise HTTPException(status_code=503, detail="求职跟进存储尚未配置")
    return CareerStore(dsn)


def _store_dep() -> CareerStore:
    return get_career_store()


Store = Annotated[CareerStore, Depends(_store_dep)]
Runtime = Annotated[object, Depends(get_runtime_dep)]
PrepStore = Annotated[PreparationStore, Depends(get_preparation_store)]


def _found(value):
    if value is None:
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    return value


# ── 看板 ──


@router.get("/board")
def list_board(user: CurrentUser, store: Store):
    return store.list_board(user["id"])


@router.put("/board/{opportunity_id}")
def update_board(opportunity_id: str, payload: BoardStatusInput, user: CurrentUser, store: Store):
    row = store.get_board_row(user["id"], opportunity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    from_stage = str(row["stage"])
    updated = store.update_board(user["id"], opportunity_id, payload.model_dump())
    if updated is not None and str(updated["stage"]) != from_stage:
        store.record_stage_change(user["id"], opportunity_id, from_stage,
                                  str(updated["stage"]), payload.note[:500])
    return _found(store.get_board_row(user["id"], opportunity_id))


@router.get("/board/{opportunity_id}/log")
def board_log(opportunity_id: str, user: CurrentUser, store: Store):
    return store.list_stage_changes(user["id"], opportunity_id)


@router.get("/opportunities/{opportunity_id}/timeline")
def opportunity_timeline(opportunity_id: str, user: CurrentUser, store: Store, prep: PrepStore):
    """岗位档案时间线：把该岗位下的收藏、版本、会话、阶段流转、任务、HR 沟通、
    Offer 与面试复盘聚合成统一事件流（按时间倒序），让一个岗位的完整过程一页可见。"""
    opportunity = prep.get_opportunity(user["id"], opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")

    events: list[dict] = []

    def add(kind: str, at: str | None, title: str, detail: str = "") -> None:
        events.append({"kind": kind, "at": at or "", "title": title, "detail": detail})

    add("created", opportunity.get("created_at"),
        f"收藏岗位：{opportunity.get('company', '')} · {opportunity.get('title', '')}")

    versions = prep.list_versions(user["id"], opportunity_id)
    for v in versions:
        add("resume_version", v.get("created_at"),
            f"简历版本「{v.get('label', '')}」",
            f"原文 {len(str(v.get('original_content') or ''))} 字 / 当前稿 {len(str(v.get('content') or ''))} 字")

    sessions = prep.list_sessions_for_opportunity(user["id"], opportunity_id)
    thread_ids: set[str] = set()
    module_label = {"resume": "简历定制", "interview": "模拟面试"}
    for s in sessions:
        thread_ids.add(str(s.get("thread_id") or ""))
        add("session", s.get("created_at"),
            f"发起{module_label.get(str(s.get('module')), '准备')}会话",
            f"使用版本「{s.get('resume_label', '')}」")

    for c in store.list_stage_changes(user["id"], opportunity_id):
        add("stage", c.get("created_at"),
            f"阶段流转：{c.get('from_stage', '')} → {c.get('to_stage', '')}",
            str(c.get("note") or ""))

    for t in store.list_tasks(user["id"], opportunity_id=opportunity_id):
        state = "已完成" if t.get("done") else "进行中"
        add("task", t.get("updated_at") or t.get("created_at"),
            f"行动任务（{state}）：{t.get('title', '')}",
            str(t.get("note") or ""))

    for f in store.list_followups(user["id"]):
        if str(f.get("opportunity_id") or "") != opportunity_id:
            continue
        add("followup", f.get("created_at"),
            f"HR 沟通：{f.get('company', '')}" + (f"（{f.get('channel')}）" if f.get("channel") else ""),
            str(f.get("content") or "")[:120])

    for o in store.list_offers(user["id"]):
        if str(o.get("opportunity_id") or "") != opportunity_id:
            continue
        add("offer", o.get("created_at"),
            f"Offer：{o.get('company', '')}",
            " / ".join(x for x in (o.get("base_salary"), o.get("bonus"), o.get("location")) if x))

    for tid in thread_ids:
        for r in store.list_interview_reports(user["id"], tid):
            report = r.get("report") if isinstance(r.get("report"), dict) else {}
            add("review", r.get("created_at"),
                "整场面试复盘报告",
                f"{report.get('scored_questions', 0)}/{report.get('total_questions', 0)} 题已评分"
                + (f"，均分 {report.get('avg_score')}" if report.get("avg_score") is not None else ""))

    events.sort(key=lambda e: str(e.get("at") or ""), reverse=True)
    return {"opportunity_id": opportunity_id, "events": events}


@router.post("/board/{opportunity_id}/archive")
def archive_opportunity(opportunity_id: str, user: CurrentUser, store: Store):
    if not store.archive_opportunity(user["id"], opportunity_id):
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    return {"ok": True}


# ── 素材库 ──


@router.get("/materials")
def list_materials(user: CurrentUser, store: Store):
    return store.list_materials(user["id"])


@router.post("/materials", status_code=201)
def create_material(payload: MaterialInput, user: CurrentUser, store: Store):
    return store.create_material(user["id"], payload.model_dump())


@router.put("/materials/{material_id}")
def update_material(material_id: str, payload: MaterialInput, user: CurrentUser, store: Store):
    return _found(store.update_material(user["id"], material_id, payload.model_dump()))


@router.delete("/materials/{material_id}")
def delete_material(material_id: str, user: CurrentUser, store: Store):
    if not store.delete_material(user["id"], material_id):
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    return {"ok": True}


# ── 行动任务 ──


class AppliedVersionRequest(BaseModel):
    applied_version_id: str = ""


@router.put("/opportunities/{opportunity_id}/applied-version")
def set_applied_version(opportunity_id: str, payload: AppliedVersionRequest,
                        user: CurrentUser, store: Store, prep: PrepStore):
    """标记投递所用简历版本（版本归因）。传空串清除标记；不改变看板阶段。"""
    if prep.get_opportunity(user["id"], opportunity_id) is None:
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    if payload.applied_version_id:
        if prep.get_version_any(user["id"], payload.applied_version_id) is None:
            raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    row = store.get_board_row(user["id"], opportunity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    from careercrew_core.career.models import BoardStatusInput

    store.update_board(user["id"], opportunity_id, BoardStatusInput(
        stage=row["stage"], next_action=row["next_action"],
        next_action_date=row["next_action_date"], note=row["note"],
        applied_version_id=payload.applied_version_id).model_dump())
    return _found(store.get_board_row(user["id"], opportunity_id))


class TaskPatch(BaseModel):
    done: bool | None = None
    postponed_due_date: str | None = None
    dismissed: bool | None = None


@router.get("/tasks")
def list_tasks(user: CurrentUser, store: Store):
    return store.list_tasks(user["id"])


@router.post("/tasks", status_code=201)
def create_task(payload: ActionItemInput, user: CurrentUser, store: Store):
    return store.create_task(user["id"], payload.model_dump())


@router.patch("/tasks/{task_id}")
def patch_task(task_id: str, payload: TaskPatch, user: CurrentUser, store: Store):
    if payload.done is None and payload.postponed_due_date is None and payload.dismissed is None:
        raise HTTPException(status_code=422, detail="没有需要更新的字段")
    row = None
    if payload.done is not None:
        row = store.complete_task(user["id"], task_id, payload.done)
        if row is not None and payload.done:
            safe_event(store.pool, user['id'], 'task_completed', 'career')
    if payload.postponed_due_date is not None:
        row = store.postpone_task(user["id"], task_id, payload.postponed_due_date)
    if payload.dismissed is not None:
        row = store.dismiss_task(user["id"], task_id, payload.dismissed)
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    return row


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, user: CurrentUser, store: Store):
    if not store.delete_task(user["id"], task_id):
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    return {"ok": True}


# ── HR 跟进 ──


@router.get("/followups")
def list_followups(user: CurrentUser, store: Store):
    return store.list_followups(user["id"])


@router.post("/followups", status_code=201)
def create_followup(payload: HRFollowupInput, user: CurrentUser, store: Store):
    return store.create_followup(user["id"], payload.model_dump())


@router.put("/followups/{followup_id}/reply-draft")
def set_reply_draft(followup_id: str, payload: HRReplyDraftInput, user: CurrentUser, store: Store):
    return _found(store.set_reply_draft(user["id"], followup_id, payload.model_dump()))


@router.post("/followups/{followup_id}/resolve")
def resolve_followup(followup_id: str, user: CurrentUser, store: Store):
    return _found(store.resolve_followup(user["id"], followup_id, True))


@router.delete("/followups/{followup_id}")
def delete_followup(followup_id: str, user: CurrentUser, store: Store):
    if not store.delete_followup(user["id"], followup_id):
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    return {"ok": True}


# ── 联系人与内推 ──


@router.get("/contacts")
def list_contacts(user: CurrentUser, store: Store):
    return store.list_contacts(user["id"])


@router.post("/contacts", status_code=201)
def create_contact(payload: ContactInput, user: CurrentUser, store: Store):
    return store.create_contact(user["id"], payload.model_dump())


@router.put("/contacts/{contact_id}")
def update_contact(contact_id: str, payload: ContactInput, user: CurrentUser, store: Store):
    return _found(store.update_contact(user["id"], contact_id, payload.model_dump()))


@router.delete("/contacts/{contact_id}")
def delete_contact(contact_id: str, user: CurrentUser, store: Store):
    if not store.delete_contact(user["id"], contact_id):
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    return {"ok": True}


# ── Offer 对比 ──


@router.get("/offers")
def list_offers(user: CurrentUser, store: Store):
    return store.list_offers(user["id"])


@router.post("/offers", status_code=201)
def create_offer(payload: OfferInput, user: CurrentUser, store: Store):
    return store.create_offer(user["id"], payload.model_dump())


@router.put("/offers/{offer_id}")
def update_offer(offer_id: str, payload: OfferInput, user: CurrentUser, store: Store):
    return _found(store.update_offer(user["id"], offer_id, payload.model_dump()))


@router.delete("/offers/{offer_id}")
def delete_offer(offer_id: str, user: CurrentUser, store: Store):
    if not store.delete_offer(user["id"], offer_id):
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    return {"ok": True}


# ── 真实面试复盘 ──


@router.get("/real-interviews")
def list_real_interviews(user: CurrentUser, store: Store):
    return store.list_real_interviews(user["id"])


@router.post("/real-interviews", status_code=201)
def create_real_interview(payload: RealInterviewInput, user: CurrentUser, store: Store):
    return store.create_real_interview(user["id"], payload.model_dump())


@router.delete("/real-interviews/{record_id}")
def delete_real_interview(record_id: str, user: CurrentUser, store: Store):
    if not store.delete_real_interview(user["id"], record_id):
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    return {"ok": True}


# ── 模拟面试整场复盘 ──


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def _within_days(date_str: str, days: int) -> bool:
    from datetime import date, timedelta

    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        return False
    return date.today() <= target <= date.today() + timedelta(days=days)


@router.get("/reminders")
def list_reminders(user: CurrentUser, store: Store):
    """聚合待办提醒：任务到期/逾期、看板下一步动作到期、未处理 HR 待办。

    提醒是派生数据（不落库）；关闭提醒 = 关闭对应任务提醒或处理完成。
    """
    today = _today()
    items: list[dict] = []
    for t in store.list_tasks(user["id"]):
        if t.get("done") or t.get("dismissed") or not t.get("due_date"):
            continue
        due = str(t["due_date"])
        if due < today:
            items.append({"kind": "task_overdue", "date": due, "title": f"任务已过期：{t['title']}",
                          "ref_id": str(t["id"])})
        elif _within_days(due, 7):
            items.append({"kind": "task_due", "date": due, "title": f"任务即将到期：{t['title']}",
                          "ref_id": str(t["id"])})
    for b in store.list_board(user["id"]):
        action_date = str(b.get("next_action_date") or "")
        action = str(b.get("next_action") or "")
        if not action or not action_date:
            continue
        label = f"{b['company']} · {b['title']}：{action}"
        if action_date < today:
            items.append({"kind": "action_overdue", "date": action_date, "title": f"跟进已逾期：{label}",
                          "ref_id": str(b["opportunity_id"])})
        elif _within_days(action_date, 7):
            items.append({"kind": "action_due", "date": action_date, "title": f"待跟进：{label}",
                          "ref_id": str(b["opportunity_id"])})
    for f in store.list_followups(user["id"]):
        if f.get("resolved") or not f.get("todo_note"):
            continue
        items.append({"kind": "followup", "date": str(f.get("received_at") or "") or today,
                      "title": f"HR 待办：{f['company']} — {f['todo_note']}",
                      "ref_id": str(f["id"])})
    for c in store.list_contacts(user["id"]):
        next_date = str(c.get("next_contact_date") or "")
        if not next_date:
            continue
        name = str(c.get("contact_name") or "")
        company = str(c.get("company") or "")
        label = f"联系 {company} {name}".strip()
        if next_date < today:
            items.append({"kind": "contact_overdue", "date": next_date,
                          "title": f"联系已逾期：{label}", "ref_id": str(c["id"])})
        elif _within_days(next_date, 7):
            items.append({"kind": "contact_due", "date": next_date,
                          "title": f"待联系：{label}", "ref_id": str(c["id"])})
    items.sort(key=lambda x: (x["date"], x["kind"]))
    return {"items": items, "today": today}


@router.get("/reminders/ics")
def reminders_ics(user: CurrentUser, store: Store):
    """导出全部带日期事项为 ICS 日历（任务截止 + 看板下一步动作），全日期事件。"""
    from datetime import UTC, datetime

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    def esc(text: str) -> str:
        return (str(text).replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CareerCrew//Reminders//CN", "CALSCALE:GREGORIAN"]
    uid_seq = 0
    for t in store.list_tasks(user["id"]):
        if t.get("done") or t.get("dismissed") or not t.get("due_date"):
            continue
        uid_seq += 1
        lines += ["BEGIN:VEVENT", f"UID:careercrew-task-{t['id']}@careercrew",
                  f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{str(t['due_date']).replace('-', '')}",
                  f"SUMMARY:{esc('[任务] ' + str(t['title']))}",
                  "END:VEVENT"]
    for b in store.list_board(user["id"]):
        action_date = str(b.get("next_action_date") or "")
        action = str(b.get("next_action") or "")
        if not action or not action_date:
            continue
        uid_seq += 1
        lines += ["BEGIN:VEVENT", f"UID:careercrew-action-{b['opportunity_id']}@careercrew",
                  f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{action_date.replace('-', '')}",
                  f"SUMMARY:{esc('[跟进] ' + str(b['company']) + ' ' + action)}",
                  "END:VEVENT"]
    for c in store.list_contacts(user["id"]):
        next_date = str(c.get("next_contact_date") or "")
        if not next_date:
            continue
        uid_seq += 1
        label = "[联系] " + " ".join(x for x in (c.get("company"), c.get("contact_name")) if x)
        lines += ["BEGIN:VEVENT", f"UID:careercrew-contact-{c['id']}@careercrew",
                  f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{next_date.replace('-', '')}",
                  f"SUMMARY:{esc(label)}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")

    body = "\r\n".join(lines) + "\r\n"
    return Response(
        body, media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=careercrew.ics",
                 "Cache-Control": "private, no-store"})


# ── ATS 简历体检（确定性规则，非 AI） ──


@router.get("/stats")
def job_search_stats(user: CurrentUser, store: Store):
    return store.job_search_stats(user["id"])


@router.get("/profile")
def get_profile(user: CurrentUser, store: Store):
    return store.get_profile(user["id"])


@router.put("/profile")
def upsert_profile(payload: CareerProfileInput, user: CurrentUser, store: Store):
    return store.upsert_profile(user["id"], payload.model_dump())


@router.get("/privacy/export")
def privacy_export(user: CurrentUser, store: Store):
    return store.export_all(user["id"])


@router.post("/privacy/purge")
def privacy_purge(user: CurrentUser, store: Store):
    return {"ok": True, "deleted": store.purge_all(user["id"])}


# 子路由依赖上方定义的 Store/Runtime 类型别名，因此在定义完成后注册。
from careercrew_api.routers import (  # noqa: E402
    career_events,
    career_generation,
    career_search,
    career_shares,
)

router.include_router(career_shares.router)
router.include_router(career_generation.router)
router.include_router(career_search.router)
router.include_router(career_events.router)
