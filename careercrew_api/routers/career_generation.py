"""Career preparation generation and deterministic checks."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.routers.career import PrepStore, Runtime, Store
from careercrew_core.career.generation_metrics import GenerationMetricInput, GenerationMetricsStore
from careercrew_core.career.product_events import safe_event
from careercrew_core.career.structured_output import (
    ApplicationKitOutput,
    GapAnalysisOutput,
    IntelligenceBriefOutput,
    InterviewReviewOutput,
    StructuredOutputError,
    parse_structured_output,
)

router = APIRouter()


def _record_generation(store, user_id: str, feature: str, source: str,
                       started: float, reason: str | None = None, llm=None) -> None:
    """Operational metadata only; metrics must never break a user workflow."""
    try:
        GenerationMetricsStore(pool=store.pool).record(GenerationMetricInput(
            owner_id=user_id, feature=feature, source=source,
            fallback_reason=reason, model=str(getattr(llm, "model_name", "") or "") or None,
            latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
        ))
    except Exception:
        logging.getLogger(__name__).warning(
            "generation_metric_write_failed feature=%s source=%s", feature, source,
        )


@router.get('/generation-metrics')
def generation_metrics(user: CurrentUser, store: Store, feature: str | None = None):
    try:
        return GenerationMetricsStore(pool=store.pool).aggregate(user['id'], feature)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail='生成指标筛选条件无效') from exc
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


def _llm_review_enhance(rt, qa: list[dict], base: dict, store, user_id: str) -> dict:
    """runtime LLM 可用时生成汇总结论；失败静默回退规则结果。"""
    llm = getattr(rt, "llm", None)
    started = time.perf_counter()
    if llm is None or not qa:
        _record_generation(store, user_id, 'interview_review', 'rules', started,
                           'no_llm' if llm is None else 'missing_input')
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
        parsed = parse_structured_output(getattr(response, "content", ""), InterviewReviewOutput)
        base.update(parsed.model_dump())
        base["source"] = "llm"
        _record_generation(store, user_id, 'interview_review', 'llm', started, llm=llm)
        return base
    except StructuredOutputError as exc:
        _record_generation(store, user_id, 'interview_review', 'rules', started, exc.reason, llm)
        return base
    except Exception:
        _record_generation(store, user_id, 'interview_review', 'rules', started, 'provider_error', llm)
        return base


@router.post("/interview-review")
def create_interview_review(payload: InterviewReviewRequest, user: CurrentUser,
                            store: Store, rt: Runtime):
    qa = _collect_interview_qa(rt, user["id"], payload.thread_id)
    report = _llm_review_enhance(rt, qa, _rule_based_report(qa), store, user["id"])
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
    started = time.perf_counter()
    reason = 'no_llm' if llm is None else ('missing_input' if not resume else None)
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
            parsed = parse_structured_output(getattr(response, "content", ""), GapAnalysisOutput)
            base = {"requirements": [item.model_dump() for item in parsed.requirements], "source": "llm"}
            _record_generation(store, user['id'], 'gap_analysis', 'llm', started, llm=llm)
            reason = None
        except StructuredOutputError as exc:
            reason = exc.reason
        except Exception:
            reason = 'provider_error'
    if base.get('source') != 'llm':
        _record_generation(store, user['id'], 'gap_analysis', 'rules', started, reason)
    saved = store.save_gap_analysis(user["id"], opportunity_id, payload.resume_version_id, base)
    return saved


@router.get("/opportunities/{opportunity_id}/gap-analysis")
def list_gap_analyses(opportunity_id: str, user: CurrentUser, store: Store):
    return store.list_gap_analyses(user["id"], opportunity_id)


# ── 提醒中心 / ICS 日历 ──



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
    started = time.perf_counter()
    reason = 'no_llm' if llm is None else ('missing_input' if not resume else None)
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
            parsed = parse_structured_output(getattr(response, "content", ""), ApplicationKitOutput)
            result = {"source": "llm", "sections": parsed.as_sections()}
            _record_generation(store, user['id'], 'application_kit', 'llm', started, llm=llm)
            safe_event(store.pool, user['id'], 'application_kit_generated', 'preparation')
            return result
        except StructuredOutputError as exc:
            reason = exc.reason
        except Exception:
            reason = 'provider_error'
    result = _template_kit(opportunity, resume)
    _record_generation(store, user['id'], 'application_kit', 'template', started, reason)
    safe_event(store.pool, user['id'], 'application_kit_generated', 'preparation')
    return result


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
    started = time.perf_counter()
    reason = 'no_llm' if llm is None else None
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
            parsed = parse_structured_output(getattr(response, "content", ""), IntelligenceBriefOutput)
            brief = {"source": "llm", **parsed.model_dump(),
                     "disclaimer": "AI 生成，外部事实未经核实，使用前请自行验证。"}
            _record_generation(store, user['id'], 'intel_brief', 'llm', started, llm=llm)
            return brief
        except StructuredOutputError as exc:
            reason = exc.reason
        except Exception:
            reason = 'provider_error'
    result = _template_brief(opportunity, resume)
    _record_generation(store, user['id'], 'intel_brief', 'template', started, reason)
    return result


# ── 统计 / 搜索 / 画像 / 隐私 ──


