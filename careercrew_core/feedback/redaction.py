"""Central redaction policy for feedback snapshots."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_VERSION = "feedback_snapshot.v1"
_MASK = "[REDACTED]"
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("phone", re.compile(r"(?<![A-Za-z0-9])(?:\+?86[- ]?)?1[3-9]\d{9}(?![A-Za-z0-9])")),
    ("china_id", re.compile(r"(?<![A-Za-z0-9])\d{17}[\dXx](?![A-Za-z0-9])")),
    ("passport", re.compile(r"\b(?:[EG]\d{8}|[A-Z]{2}\d{7})\b")),
    ("api_key", re.compile(r"\b(?:sk|pk|rk|AKIA)[-_A-Za-z0-9]{8,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]+")),
    ("credential", re.compile(r"(?i)\b(?:access[_-]?key|secret|password|passwd|token|api[_-]?key)\s*[:=]\s*\S+")),
    ("database_url", re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s]+")),
    ("windows_path", re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:\\(?:[^\s<>:\"|?*\\;]+\\?)*[^\s<>:\"|?*\\;]*")),
    ("unix_path", re.compile(r"(?<!\w)/(?:home|Users|opt|srv|mnt|tmp|var|etc)(?=$|[/\s'\"<>;])(?:/[^\s'\"<>;]*)?")),
    ("user_home", re.compile(r"(?i)(?:~[\\/]|%USERPROFILE%[\\/]|\$HOME[\\/])[^\s'\"<>;]*")),
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    count: int
    rule_ids: list[str]
    version: str = _VERSION


def redact(text: str, profile: str = "feedback_snapshot") -> RedactionResult:
    """Redact a string under the named privacy profile, recording matched rules."""
    if profile != "feedback_snapshot":
        raise ValueError(f"unknown redaction profile: {profile}")
    output, count, matched = text or "", 0, []
    for rule_id, pattern in _RULES:
        output, replacements = pattern.subn(_MASK, output)
        if replacements:
            count += replacements
            matched.append(rule_id)
    return RedactionResult(output, count, matched)


def redact_value(value: Any, profile: str = "feedback_snapshot") -> tuple[Any, int, list[str], str]:
    """Recursively redact every text value without retaining its source value."""
    if isinstance(value, str):
        result = redact(value, profile)
        return result.text, result.count, result.rule_ids, result.version
    if isinstance(value, list):
        output, count, rules, version = [], 0, [], _VERSION
        for item in value:
            redacted, n, ids, version = redact_value(item, profile)
            output.append(redacted)
            count += n
            rules.extend(rule for rule in ids if rule not in rules)
        return output, count, rules, version
    if isinstance(value, dict):
        output, count, rules, version = {}, 0, [], _VERSION
        for key, item in value.items():
            redacted, n, ids, version = redact_value(item, profile)
            output[key] = redacted
            count += n
            rules.extend(rule for rule in ids if rule not in rules)
        return output, count, rules, version
    return value, 0, [], _VERSION
