"""写入前脱敏：识别并打码常见 secret（API key / token / 密码 / 手机号 / 邮箱）。"""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
]

_MASK = "[REDACTED]"


def redact_secrets(text: str) -> str:
    """把文本里的 secret 模式替换为 [REDACTED]。"""
    if not text:
        return text
    out = text
    for pat in _PATTERNS:
        out = pat.sub(_MASK, out)
    return out


def redact_content(content: dict | str) -> dict | str:
    """递归脱敏 memory content（dict 值 / 字符串值）。"""
    if isinstance(content, str):
        return redact_secrets(content)
    if isinstance(content, dict):
        return {k: redact_content(v) for k, v in content.items()}
    if isinstance(content, list):
        return [redact_content(v) for v in content]
    return content
