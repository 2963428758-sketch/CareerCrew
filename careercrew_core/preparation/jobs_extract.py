"""从成功 search_jobs 工具的结构化返回中提取岗位卡片数据。

只信任服务端工具的结构化结果（artifact / JSON 字符串），绝不从 LLM 的
Markdown 回答里猜测岗位。长度上限与链接安全在这里统一约束，保证提取结果
可以直接通过 /api/preparation 的输入校验收藏为岗位。
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

# 单次对话最多携带的岗位数与单条 JD 上限（与 OpportunityInput 校验对齐）
MAX_JOBS = 20
MAX_JD_CHARS = 30000

_TOOL_NAME = "search_jobs"


def _safe_url(url) -> str:
    """只放行 HTTP/HTTPS 绝对链接；其余一律降级为空串（不导航）。"""
    text = str(url or "").strip()
    if not text or any(char.isspace() for char in text):
        return ""
    try:
        parsed = urlsplit(text)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return ""
    except ValueError:
        return ""
    return text


def _dedup_key(item: dict) -> tuple:
    source = str(item.get("source") or "").strip().lower()
    url = str(item.get("url") or "").strip().lower()
    if url:
        return (source, url)
    return (
        source,
        str(item.get("company") or "").strip().lower(),
        str(item.get("title") or "").strip().lower(),
        str(item.get("city") or "").strip().lower(),
    )


def _normalize_job(raw) -> dict | None:
    if not isinstance(raw, dict) or "error" in raw:
        return None
    company = str(raw.get("company") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not company or not title:
        return None
    return {
        "company": company,
        "title": title,
        "city": str(raw.get("city") or "").strip(),
        "salary": str(raw.get("salary") or "").strip(),
        "experience": str(raw.get("experience") or "").strip(),
        "source": str(raw.get("source") or "").strip().lower(),
        "source_label": str(raw.get("source_label") or "").strip(),
        "retrieval_mode": str(raw.get("retrieval_mode") or "").strip(),
        "retrieval_mode_label": str(raw.get("retrieval_mode_label") or "").strip(),
        "matched_core_terms": [str(t) for t in (raw.get("matched_core_terms") or [])
                               if str(t).strip()][:10],
        "url": _safe_url(raw.get("url")),
        "jd": str(raw.get("jd") or "")[:MAX_JD_CHARS],
    }


def _jobs_from_payload(payload):
    """artifact / 解析后的 JSON 都必须是岗位 dict 列表；错误列表自然被过滤。"""
    if not isinstance(payload, list):
        return []
    normalized = []
    for raw in payload:
        job = _normalize_job(raw)
        if job is not None:
            normalized.append(job)
    return normalized


def _parse_json_payload(content):
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text.startswith("["):
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _dedup_append(jobs: list[dict], seen: set, candidates) -> None:
    for job in candidates:
        key = _dedup_key(job)
        if key in seen:
            continue
        seen.add(key)
        jobs.append(job)
        if len(jobs) >= MAX_JOBS:
            return


def extract_jobs_from_agent_result(result) -> list[dict]:
    """从 AgentResult（或任何带 iterations 属性的对象）提取去重后的岗位列表。"""
    iterations = list(getattr(result, "iterations", None) or [])
    jobs: list[dict] = []
    seen: set[tuple] = set()

    named_seen = False
    for iteration in iterations:
        for record in getattr(iteration, "tool_results_named", None) or []:
            if not isinstance(record, dict) or record.get("name") != _TOOL_NAME:
                continue
            named_seen = True
            payload = record.get("artifact")
            if payload is None:
                payload = _parse_json_payload(record.get("content"))
            _dedup_append(jobs, seen, _jobs_from_payload(payload))
            if len(jobs) >= MAX_JOBS:
                return jobs

    if not named_seen:
        # 兼容没有具名结果记录的旧路径：迭代内 tool_calls 与 tool_results 按序
        # 对应；JSON 解析失败（如超长截断）的自然跳过。
        for iteration in iterations:
            names = {tc.get("name") for tc in (getattr(iteration, "tool_calls", None) or [])
                     if isinstance(tc, dict)}
            if _TOOL_NAME not in names:
                continue
            for raw in getattr(iteration, "tool_results", None) or []:
                payload = _parse_json_payload(raw)
                if payload is None:
                    continue
                _dedup_append(jobs, seen, _jobs_from_payload(payload))
                if len(jobs) >= MAX_JOBS:
                    return jobs
    return jobs
