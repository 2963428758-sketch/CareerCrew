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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.routers.preparation import get_preparation_store
from careercrew_core.career.models import (
    ActionItemInput,
    BoardStatusInput,
    CareerProfileInput,
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
