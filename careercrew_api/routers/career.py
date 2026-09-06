"""求职持续跟进 API（第二/三期）：看板、素材库、行动任务、HR 跟进、Offer 对比、
真实面试复盘、面试复盘报告、可解释匹配、统计、全局搜索、画像与隐私控制。

与 /api/preparation 一样走独立 CareerStore 依赖，不依赖任何 LLM 运行时；
gap-analysis 与面试复盘报告在 runtime.llm 可用时做语义增强，否则规则兜底。
"""
from __future__ import annotations

import json
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


class InterviewReviewRequest(BaseModel):
    thread_id: str


def _collect_interview_qa(rt, user_id: str, thread_id: str) -> list[dict]:
    """从会话历史抽取（问题、回答、分数、反馈）；分数来自逐题评分解析。"""
    from careercrew_core.agents.interviewer import _parse_score

    rows = rt.conversation_store.list_messages(thread_id, user_id)
    qa: list[dict] = []
    last_question = ""
    for row in rows:
        content = str(row.get("content") or "")
        if not content:
            continue
        if row.get("role") == "assistant":
            parsed = _parse_score(content, 10)
            qa.append({
                "question": last_question,
                "answer_excerpt": "",
                "score": parsed.get("score"),
                "feedback": parsed.get("feedback") or "",
                "assistant_text": content[:2000],
            })
        elif row.get("role") == "user":
            last_question = ""
            qa.append({"user_answer": content[:5000]})
    return _pair_qa(qa)


def _pair_qa(flat: list[dict]) -> list[dict]:
    """把交替的 user/assistant 行组合成 {question, answer, score, feedback}。"""
    paired: list[dict] = []
    pending_answer = ""
    for item in flat:
        if "user_answer" in item:
            pending_answer = item["user_answer"]
        elif pending_answer or item.get("score") is not None:
            paired.append({
                "question": item.get("question") or "",
                "answer": pending_answer,
                "score": item.get("score"),
                "feedback": item.get("feedback") or "",
                "assistant_text": item.get("assistant_text") or "",
            })
            pending_answer = ""
    return paired


def _rule_based_report(qa: list[dict]) -> dict:
    scored = [item for item in qa if isinstance(item.get("score"), (int, float))]
    scores = [float(item["score"]) for item in scored]
    weaknesses = [
        {"question": item.get("question") or (item.get("assistant_text") or "")[:80],
         "score": item.get("score"), "feedback": item.get("feedback") or ""}
        for item in scored if float(item["score"]) <= (min(scores) if scores else 0) + 1
    ][:3]
    strengths = [
        {"question": item.get("question") or (item.get("assistant_text") or "")[:80],
         "score": item.get("score"), "feedback": item.get("feedback") or ""}
        for item in scored if float(item["score"]) >= (max(scores) if scores else 0) - 1
    ][:3]
    return {
        "total_questions": len(qa),
        "scored_questions": len(scored),
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "by_question": [
            {"question": item.get("question") or (item.get("assistant_text") or "")[:80],
             "answer": item.get("answer") or "",
             "score": item.get("score"), "feedback": item.get("feedback") or ""}
            for item in qa
        ],
        "source": "rules",
    }


def _llm_review_enhance(rt, qa: list[dict], base: dict) -> dict:
    """runtime LLM 可用时生成汇总结论；失败静默回退规则结果。"""
    llm = getattr(rt, "llm", None)
    if llm is None or not qa:
        return base
    transcript = "\n".join(
        f"问：{item.get('question') or ''}\n答：{(item.get('answer') or '')[:500]}\n"
        f"评分：{item.get('score')}\n反馈：{item.get('feedback') or ''}"
        for item in qa[:20])
    prompt = (
        "你是面试教练。请基于以下模拟面试记录输出 JSON（不要多余文字）：\n"
        '{"summary": "两句话总评", "strengths": ["优势1(引用回答原文短语)"],'
        ' "weaknesses": ["薄弱点1(引用回答原文短语)"], "practice_suggestions": ["练习建议1"]}\n'
        "要求：优势与薄弱点各不超过3条，必须引用实际回答作为证据。\n\n"
        f"{transcript}")
    try:
        response = llm.invoke(prompt)
        raw = getattr(response, "content", "")
        if isinstance(raw, list):
            raw = "".join(str(p.get("text") or "") for p in raw if isinstance(p, dict))
        text = str(raw).strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return base
        parsed = json.loads(text[start:end + 1])
        base["summary"] = str(parsed.get("summary") or "")[:500]
        base["strengths"] = [str(s)[:300] for s in (parsed.get("strengths") or [])][:3] or base["strengths"]
        base["weaknesses"] = [str(s)[:300] for s in (parsed.get("weaknesses") or [])][:3] or base["weaknesses"]
        base["practice_suggestions"] = [str(s)[:300] for s in (parsed.get("practice_suggestions") or [])][:3]
        base["source"] = "llm"
        return base
    except Exception:  # noqa: BLE001 - LLM 不可用不影响复盘落库
        return base


@router.post("/interview-review")
def create_interview_review(payload: InterviewReviewRequest, user: CurrentUser,
                            store: Store, rt: Runtime):
    qa = _collect_interview_qa(rt, user["id"], payload.thread_id)
    report = _llm_review_enhance(rt, qa, _rule_based_report(qa))
    saved = store.save_interview_report(user["id"], payload.thread_id, report)
    return saved


@router.get("/interview-reports")
def list_interview_reports(user: CurrentUser, store: Store, thread_id: str | None = None):
    return store.list_interview_reports(user["id"], thread_id)


# ── 可解释岗位匹配 / 技能差距 ──


class GapAnalysisRequest(BaseModel):
    resume_version_id: str = ""


def _rule_based_gap(jd: str, resume: str) -> dict:
    """确定性兜底：按 JD 行/句子拆要求，判断简历是否提供证据。"""
    requirements = []
    for raw in jd.replace("；", "\n").replace(";", "\n").replace("。", "\n").split("\n"):
        text = raw.strip(" -•*\t")
        if not (2 <= len(text) <= 200):
            continue
        keywords = [ch for ch in ("懂", "熟悉", "掌握", "了解", "经验", "优先") if ch in text]
        evidence = any(
            token and token in resume
            for token in ([text[:6]] if len(text) >= 6 else [text])
        )
        requirements.append({
            "requirement": text[:200],
            "status": "matched" if evidence else "not_mention",
            "note": "简历未提供该要求的直接证据" if not evidence else "",
            "keyword_hint": bool(keywords),
        })
        if len(requirements) >= 15:
            break
    return {"requirements": requirements, "source": "rules"}


@router.post("/opportunities/{opportunity_id}/gap-analysis", status_code=201)
def create_gap_analysis(opportunity_id: str, payload: GapAnalysisRequest,
                        user: CurrentUser, store: Store, rt: Runtime, prep: PrepStore):
    opportunity = prep.get_opportunity(user["id"], opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="岗位、简历版本或准备会话不存在")
    resume = ""
    if payload.resume_version_id:
        version = prep.get_version(user["id"], opportunity_id, payload.resume_version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="岗位、简历版本或准备会话不存在")
        resume = str(version.get("content") or "")
    jd = str(opportunity.get("jd") or "")
    base = _rule_based_gap(jd, resume)
    llm = getattr(rt, "llm", None)
    if llm is not None and resume:
        prompt = (
            "你是招聘官。请对比目标 JD 与候选人简历，输出 JSON（不要多余文字）：\n"
            '{"requirements": [{"requirement": "JD 要求", "status": "matched|missing|not_mention",'
            ' "evidence": "简历原文短语或空", "note": "一句话说明"}]}\n'
            "status 定义：matched=简历提供了证据；missing=简历明确没有该能力；"
            "not_mention=简历未提及（不代表没有）。要求逐条来自 JD，最多12条。\n\n"
            f"【JD】\n{jd[:6000]}\n\n【简历】\n{resume[:6000]}")
        try:
            response = llm.invoke(prompt)
            raw = getattr(response, "content", "")
            if isinstance(raw, list):
                raw = "".join(str(p.get("text") or "") for p in raw if isinstance(p, dict))
            text = str(raw).strip()
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                parsed = json.loads(text[start:end + 1])
                items = parsed.get("requirements")
                if isinstance(items, list) and items:
                    cleaned = [{
                        "requirement": str(i.get("requirement") or "")[:200],
                        "status": str(i.get("status") or "not_mention"),
                        "evidence": str(i.get("evidence") or "")[:300],
                        "note": str(i.get("note") or "")[:300],
                    } for i in items if isinstance(i, dict)][:12]
                    base = {"requirements": cleaned, "source": "llm"}
        except Exception:  # noqa: BLE001 - LLM 失败回退规则结果
            pass
    saved = store.save_gap_analysis(user["id"], opportunity_id, payload.resume_version_id, base)
    return saved


@router.get("/opportunities/{opportunity_id}/gap-analysis")
def list_gap_analyses(opportunity_id: str, user: CurrentUser, store: Store):
    return store.list_gap_analyses(user["id"], opportunity_id)


# ── 提醒中心 / ICS 日历 ──


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


class AtsCheckRequest(BaseModel):
    resume_version_id: str = ""
    jd: str = ""


def _ats_checks(resume: str, jd: str) -> dict:
    import re

    checks: list[dict] = []

    def add(item: str, ok: bool, note: str) -> None:
        checks.append({"item": item, "status": "pass" if ok else "warn", "note": note})

    add("联系方式：邮箱", bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", resume)),
        "未找到邮箱，HR 无法联系你" if not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", resume) else "")
    add("联系方式：手机号", bool(re.search(r"1[3-9]\d{9}", resume)),
        "" if re.search(r"1[3-9]\d{9}", resume) else "未找到 11 位手机号")
    sections = {"教育": "教育", "工作经历": ("工作", "职业经历", "实习"), "项目经历": ("项目", "实践"),
                "技能": ("技能", "技术栈", "专业技能")}
    for name, keys in sections.items():
        keys = keys if isinstance(keys, tuple) else (keys,)
        present = any(k in resume for k in keys)
        add(f"章节：{name}", present, "" if present else f"建议补充「{name}」章节")
    years = re.findall(r"(?:19|20)\d{2}", resume)
    add("时间线：年份", len(years) >= 2,
        "" if len(years) >= 2 else "几乎没有年份信息，经历时间线不清晰")
    quantified = re.findall(r"\d+(?:\.\d+)?\s*[%％]|[+\-]?\d+(?:\.\d+)?\s*(?:万|w|k|K|QPS|倍|ms|秒)", resume)
    add("量化成果", len(quantified) >= 2,
        f"检测到 {len(quantified)} 处量化数据" + ("" if len(quantified) >= 2 else "，建议补充百分比/规模等量化成果"))
    length = len(resume.strip())
    add("篇幅", 300 <= length <= 6000,
        f"{length} 字" + ("" if 300 <= length <= 6000 else "，过短或过长都会影响阅读"))

    coverage = None
    if jd.strip():
        lines = [seg.strip(" -•*\t；;，,。") for seg in re.split(r"[。\n；;]", jd) if 4 <= len(seg.strip()) <= 120]
        hit = sum(1 for seg in lines[:12] if any(token and token in resume for token in [seg[:6]]))
        coverage = {"requirements": min(len(lines), 12), "covered": hit}
    return {"checks": checks, "jd_coverage": coverage, "source": "rules"}


@router.post("/opportunities/{opportunity_id}/ats-check")
def ats_check(opportunity_id: str, payload: AtsCheckRequest,
              user: CurrentUser, store: Store, prep: PrepStore):
    """确定性 ATS 体检：只跑规则（联系方式/章节/时间线/量化/篇幅/JD 覆盖），
    不调用 LLM；结果明确标注 source=rules。"""
    opportunity = prep.get_opportunity(user["id"], opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    resume = ""
    if payload.resume_version_id:
        version = prep.get_version(user["id"], opportunity_id, payload.resume_version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
        resume = str(version.get("content") or "")
    jd = payload.jd.strip() or str(opportunity.get("jd") or "")
    return _ats_checks(resume, jd)


# ── 岗位专属投递材料包 ──


class ApplicationKitRequest(BaseModel):
    resume_version_id: str = ""


_KIT_TEMPLATE = (
    "【求职信】\n"
    "您好！我看到贵司「{title}」岗位与我的方向高度契合。我有 {highlight}，"
    "与 JD 中的核心要求（{jd_head}）直接对应，希望有机会进一步沟通。\n\n"
    "【自我介绍（30 秒）】\n"
    "面试官您好，我叫我（自行替换姓名），主要做{highlight}。"
    "看到这个岗位需要{jd_head}，这正是我过去一年的主线工作。\n\n"
    "【Boss 招呼语】\n"
    "您好，看到贵司「{title}」岗位。我有{highlight}，与 JD 匹配度较高，方便发一份完整简历给您看看吗？\n\n"
    "【HR 跟进话术】\n"
    "您好，想跟进一下「{title}」岗位的进展。我这边时间比较灵活，可以配合安排面试，谢谢！\n\n"
    "【面试后感谢信】\n"
    "感谢今天和您交流「{title}」岗位，聊到的{jd_head}让我很有共鸣，也更坚定了加入的意愿。"
    "期待后续消息，祝工作顺利！"
)


def _template_kit(opportunity: dict, resume: str) -> dict:
    """规则模板兜底：无 LLM 或调用失败时也能产出可用的初稿。"""
    highlight = ""
    import re

    hits = re.findall(r"[^\n，。；]*(?:准确率|召回|QPS|延迟|日活|用户)[^\n，。；]*", resume)
    if hits:
        highlight = hits[0].strip()[:60]
    if not highlight:
        skills = re.search(r"技能[：:][^\n]+", resume)
        highlight = skills.group(0)[3:].strip()[:60] if skills else "相关的后端与大模型应用经验"
    jd_head = re.split(r"[。\n；;]", str(opportunity.get("jd") or ""))[0][:60]
    body = _KIT_TEMPLATE.format(title=opportunity.get("title", ""), highlight=highlight, jd_head=jd_head)
    markers = ["【求职信】", "【自我介绍（30 秒）】", "【Boss 招呼语】", "【HR 跟进话术】", "【面试后感谢信】"]
    keys = ["cover_letter", "self_intro", "greeting", "followup", "thank_you"]
    sections: dict[str, str] = {}
    for i, marker in enumerate(markers):
        begin = body.find(marker)
        stop = body.find(markers[i + 1]) if i + 1 < len(markers) else len(body)
        sections[keys[i]] = body[begin + len(marker):stop].strip() if begin != -1 and stop != -1 else ""
    return {"source": "template", "sections": sections}


@router.post("/opportunities/{opportunity_id}/application-kit", status_code=201)
def create_application_kit(opportunity_id: str, payload: ApplicationKitRequest,
                           user: CurrentUser, store: Store, rt: Runtime, prep: PrepStore):
    """生成岗位专属投递材料包（求职信/自我介绍/招呼语/跟进话术/感谢信）。

    LLM 可用时语义生成，失败回退规则模板；只产出草稿，发送始终由用户完成。
    """
    opportunity = prep.get_opportunity(user["id"], opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    resume = ""
    if payload.resume_version_id:
        version = prep.get_version(user["id"], opportunity_id, payload.resume_version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
        resume = str(version.get("content") or "")

    llm = getattr(rt, "llm", None)
    if llm is not None and resume:
        prompt = (
            "你是求职教练。基于岗位 JD 与候选人简历，输出 JSON（不要多余文字）：\n"
            '{"cover_letter": "150字内求职信", "self_intro": "30秒自我介绍", '
            '"greeting": "Boss直聘招呼语（80字内）", "followup": "HR 跟进话术（60字内）", '
            '"thank_you": "面试后感谢信（100字内）"}\n'
            "要求：引用简历中的真实量化成果，不编造经历。\n\n"
            f"【JD】\n{str(opportunity.get('jd') or '')[:5000]}\n\n【简历】\n{resume[:5000]}")
        try:
            response = llm.invoke(prompt)
            raw = getattr(response, "content", "")
            if isinstance(raw, list):
                raw = "".join(str(p.get("text") or "") for p in raw if isinstance(p, dict))
            text = str(raw).strip()
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                parsed = json.loads(text[start:end + 1])
                sections = {k: str(parsed.get(k) or "")[:2000] for k in
                            ("cover_letter", "self_intro", "greeting", "followup", "thank_you")}
                if any(sections.values()):
                    return {"source": "llm", "sections": sections}
        except Exception:  # noqa: BLE001 - LLM 失败回退模板
            pass
    return _template_kit(opportunity, resume)


# ── 导师只读分享 ──


class ShareCreateRequest(BaseModel):
    kind: str
    ref_id: str
    expires_days: int = 7
    mask_pii: bool = False


def _mask_pii_text(text: str) -> str:
    import re

    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[邮箱已隐藏]", text)
    text = re.sub(r"1[3-9]\d{9}", "[手机号已隐藏]", text)
    return text


def _share_payload(row: dict, prep) -> dict:
    """构造公开只读载荷：仅必要字段；mask_pii 时对文本做 PII 脱敏。"""
    prep = prep
    owner = str(row["owner_id"])
    mask = bool(row["mask_pii"])

    def clean(text) -> str:
        text = str(text or "")
        return _mask_pii_text(text) if mask else text

    if row["kind"] == "resume_version":
        version = prep.get_version_any(owner, str(row["ref_id"]))
        if version is None:
            return {"kind": "resume_version", "missing": True}
        return {"kind": "resume_version", "label": clean(version.get("label")),
                "content": clean(version.get("content")),
                "created_at": version.get("created_at")}
    opportunity = prep.get_opportunity(owner, str(row["ref_id"]))
    if opportunity is None:
        return {"kind": "opportunity", "missing": True}
    versions = list(prep.list_versions(owner, str(opportunity["id"])))
    return {
        "kind": "opportunity",
        "company": clean(opportunity.get("company")),
        "title": clean(opportunity.get("title")),
        "jd": clean(opportunity.get("jd")),
        "city": clean(opportunity.get("city")),
        "salary": clean(opportunity.get("salary")),
        "stage": clean(opportunity.get("stage")),
        "versions": [{"label": clean(v.get("label")), "content": clean(v.get("content")),
                      "created_at": v.get("created_at")} for v in versions],
    }


@router.post("/shares", status_code=201)
def create_share(payload: ShareCreateRequest, user: CurrentUser, store: Store, prep: PrepStore):
    """创建导师只读分享链接。kind=opportunity 分享整包；kind=resume_version 只分享单版本。"""
    if payload.kind not in ("opportunity", "resume_version"):
        raise HTTPException(status_code=422, detail="kind 必须为 opportunity 或 resume_version")
    if not 1 <= payload.expires_days <= 30:
        raise HTTPException(status_code=422, detail="有效期 1-30 天")
    if payload.kind == "opportunity":
        if prep.get_opportunity(user["id"], payload.ref_id) is None:
            raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    else:
        if prep.get_version_any(user["id"], payload.ref_id) is None:
            raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    from datetime import timedelta

    expires = (datetime_now_utc() + timedelta(days=payload.expires_days)).isoformat()
    row = store.create_share(user["id"], payload.kind, payload.ref_id, expires, payload.mask_pii)
    return {"token": row["token"], "kind": row["kind"], "ref_id": row["ref_id"],
            "mask_pii": bool(row["mask_pii"]), "expires_at": row["expires_at"]}


@router.get("/shares")
def list_shares(user: CurrentUser, store: Store):
    return store.list_shares(user["id"])


@router.delete("/shares/{token}")
def revoke_share(token: str, user: CurrentUser, store: Store):
    if not store.revoke_share(user["id"], token):
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    return {"ok": True}


@router.get("/share/{token}")
def resolve_share(token: str, store: Store, prep: PrepStore):
    """公开只读访问（无鉴权）：令牌过期/撤销/不存在一律 404。"""
    row = store.resolve_share(token)
    if row is None:
        raise HTTPException(status_code=404, detail="分享不存在或已失效")
    payload = _share_payload(row, prep)
    if payload.get("missing"):
        raise HTTPException(status_code=404, detail="分享内容不存在或已失效")
    return {"mask_pii": bool(row["mask_pii"]), "expires_at": row["expires_at"], **payload}


def datetime_now_utc():
    from datetime import UTC, datetime

    return datetime.now(UTC)


# ── 公司与面试情报包 ──


class IntelBriefRequest(BaseModel):
    resume_version_id: str = ""


def _template_brief(opportunity: dict, resume: str) -> dict:
    import re

    jd = str(opportunity.get("jd") or "")
    lines = [seg.strip(" -•*\t；;，,") for seg in re.split(r"[。\n]", jd) if 6 <= len(seg.strip()) <= 120][:6]
    quantified = re.findall(r"[^\n，。；]*(?:准确率|召回|QPS|延迟)[^\n，。；]*", resume)
    likely = [f"请结合你的经历谈谈对该要求的理解：{seg[:60]}" for seg in lines[:3]]
    if not likely:
        likely = ["请自我介绍并重点讲与岗位最相关的一段经历"]
    confirm = [
        "团队规模与分工？这个岗位补的是哪块能力？",
        "入职后前三个月的预期产出是什么？",
        "技术栈与团队现有工作流的衔接方式？",
    ]
    return {
        "source": "template",
        "company_research": f"基于 JD 推断的业务方向：{jd[:80]}（未联网核实，请自行查证公司官网/新闻）",
        "likely_questions": likely,
        "confirm_questions": confirm,
        "evidence": quantified[:2],
        "disclaimer": "本情报包由 AI/规则生成，外部事实未经核实，使用前请自行验证。",
    }


@router.post("/opportunities/{opportunity_id}/intel-brief", status_code=201)
def create_intel_brief(opportunity_id: str, payload: IntelBriefRequest,
                       user: CurrentUser, store: Store, rt: Runtime, prep: PrepStore):
    """公司与面试情报包：汇总岗位要点、可能问题与待向面试官确认的问题。

    外部事实类内容为 AI 推断，明确标注需自行核实（不冒充已验证信息）。
    """
    opportunity = prep.get_opportunity(user["id"], opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
    resume = ""
    if payload.resume_version_id:
        version = prep.get_version(user["id"], opportunity_id, payload.resume_version_id)
        if version is None:
            raise HTTPException(status_code=404, detail="记录不存在或不属于当前账号")
        resume = str(version.get("content") or "")

    llm = getattr(rt, "llm", None)
    if llm is not None:
        prompt = (
            "你是求职教练。基于 JD 与简历生成面试前情报包 JSON（不要多余文字）：\n"
            '{"company_research": "基于 JD 推断的公司业务与方向（100字内，注明这是推断）", '
            '"likely_questions": ["面试官最可能问的 3 个问题"], '
            '"confirm_questions": ["应向面试官确认的 3 个问题"], '
            '"evidence": ["简历中可用的量化证据"]}\n\n'
            "【JD】\n" + str(opportunity.get("jd") or "")[:5000] + "\n\n【简历】\n" + resume[:4000])
        try:
            response = llm.invoke(prompt)
            raw = getattr(response, "content", "")
            if isinstance(raw, list):
                raw = "".join(str(p.get("text") or "") for p in raw if isinstance(p, dict))
            text = str(raw).strip()
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                parsed = json.loads(text[start:end + 1])
                brief = {
                    "source": "llm",
                    "company_research": str(parsed.get("company_research") or "")[:600],
                    "likely_questions": [str(q)[:300] for q in (parsed.get("likely_questions") or [])][:4],
                    "confirm_questions": [str(q)[:300] for q in (parsed.get("confirm_questions") or [])][:4],
                    "evidence": [str(q)[:300] for q in (parsed.get("evidence") or [])][:4],
                    "disclaimer": "AI 生成，外部事实未经核实，使用前请自行验证。",
                }
                if brief["likely_questions"]:
                    return brief
        except Exception:  # noqa: BLE001 - LLM 失败回退模板
            pass
    return _template_brief(opportunity, resume)


# ── 统计 / 搜索 / 画像 / 隐私 ──


@router.get("/stats")
def job_search_stats(user: CurrentUser, store: Store):
    return store.job_search_stats(user["id"])


@router.get("/search")
def global_search(q: str, user: CurrentUser, store: Store):
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="搜索词不能为空")
    return store.global_search(user["id"], query[:200])


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
