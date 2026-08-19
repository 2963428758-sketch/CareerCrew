"""对话导出（§13.2/§13.3）：纯函数，从 conversation 行 + messages + runs 构造 MD/JSON 文本。

安全红线：导出内容**绝不包含** token / system prompt / agent secret / 内部 Tool credential /
其他用户信息。只从白名单字段拼装（title、role、content、sources、run 的
model/prompt_version/agent_version/latency_ms）。full system prompt / tool raw output /
hidden trace 本就不在这些表里，此处额外做字段白名单兜底。
"""
from __future__ import annotations

import json
from typing import Any

# 导出 JSON 里 run 子对象允许的白名单字段（§13.3）
_RUN_FIELDS = ("model", "prompt_version", "agent_version", "latency_ms")

# 敏感子串哨兵：任何命中都视为意外泄露（防御性校验，正常数据不应含这些）
_SENSITIVE_MARKERS = ("system_prompt", "api_key", "token", "secret", "credential")


def _redact_sources(metadata: dict | None) -> list[dict]:
    """从 assistant 消息 metadata 抽取 sources（白名单字段：doc/source/score/text/image_path/page）。"""
    if not metadata:
        return []
    sources = metadata.get("sources")
    if not isinstance(sources, list):
        return []
    out: list[dict] = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        out.append({
            k: s.get(k) for k in ("doc", "source", "score", "text", "image_path", "page")
            if k in s
        })
    return out


def _clean_run(run: dict | None) -> dict:
    if not run:
        return {}
    return {k: run.get(k) for k in _RUN_FIELDS if run.get(k) is not None}


def _assert_no_sensitive(text: str) -> None:
    low = text.lower()
    for marker in _SENSITIVE_MARKERS:
        if marker in low:
            raise ValueError(f"导出内容疑似包含敏感字段「{marker}」，已拒绝导出")


def build_markdown(conversation: dict, messages: list[dict]) -> str:
    """构造 Markdown：`# Title` → 每条 `## User` / `## Assistant`（含 `### Sources`）。

    仅渲染 role 白名单（user/assistant）；content 原文；assistant 的 sources 追加
    `### Sources` 小节。
    """
    title = conversation.get("title") or conversation.get("id") or "未命名会话"
    lines: list[str] = [f"# {title}", ""]
    for m in messages:
        role = (m.get("role") or "").lower()
        if role == "user":
            lines.append("## User")
        elif role == "assistant":
            lines.append("## Assistant")
        else:
            continue
        content = m.get("content") or ""
        lines.append("")
        lines.append(content)
        lines.append("")
        if role == "assistant":
            sources = _redact_sources(m.get("metadata"))
            if sources:
                lines.append("### Sources")
                lines.append("")
                for s in sources:
                    doc = s.get("doc") or s.get("source") or ""
                    lines.append(f"- {doc}")
                lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    _assert_no_sensitive(text)
    return text


def build_json(conversation: dict, messages: list[dict], runs: list[dict]) -> dict:
    """构造导出 JSON 结构：{thread, messages, sources, runs:[{model, prompt_version,
    agent_version, latency_ms}]}。

    返回 dict（可再序列化）；messages 只保留白名单字段（role/content/sources），
    剔除 run_id/regenerated_from_message_id/metadata 原样（避免泄露内部追踪信息）。
    """
    msgs: list[dict] = []
    for m in messages:
        role = (m.get("role") or "").lower()
        if role not in ("user", "assistant"):
            continue
        entry: dict[str, Any] = {
            "role": role,
            "content": m.get("content") or "",
        }
        if role == "assistant":
            sources = _redact_sources(m.get("metadata"))
            if sources:
                entry["sources"] = sources
        msgs.append(entry)

    sources: list[dict] = []
    for m in messages:
        if (m.get("role") or "").lower() == "assistant":
            sources.extend(_redact_sources(m.get("metadata")))

    payload = {
        "thread": {
            "id": conversation.get("id"),
            "title": conversation.get("title"),
            "module": conversation.get("module"),
            "created_at": conversation.get("created_at"),
        },
        "messages": msgs,
        "sources": sources,
        "runs": [_clean_run(r) for r in runs],
    }
    # 序列化后做敏感字段红线校验（覆盖嵌套内容）
    _assert_no_sensitive(json.dumps(payload, ensure_ascii=False, default=str))
    return payload


def build_json_text(conversation: dict, messages: list[dict], runs: list[dict]) -> str:
    """build_json 的文本序列化版本（供路由直接返回）。"""
    return json.dumps(build_json(conversation, messages, runs), ensure_ascii=False, indent=2, default=str)
