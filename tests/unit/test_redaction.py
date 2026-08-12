"""写入前脱敏测试。"""
from __future__ import annotations

from careercrew_core.memory.redaction import redact_content, redact_secrets


def test_redacts_api_key() -> None:
    assert "sk-abcdef1234567890" not in redact_secrets("key=sk-abcdef1234567890")
    assert "[REDACTED]" in redact_secrets("key=sk-abcdef1234567890")


def test_redacts_phone_and_email() -> None:
    out = redact_secrets("电话 13800138000，邮箱 a@b.com")
    assert "13800138000" not in out
    assert "a@b.com" not in out


def test_redact_content_recursive() -> None:
    out = redact_content({"token": "sk-abcdef1234567890", "items": ["13800138000", "ok"]})
    assert out["token"] == "[REDACTED]"
    assert out["items"][0] == "[REDACTED]"
    assert out["items"][1] == "ok"


def test_empty_ok() -> None:
    assert redact_secrets("") == ""
    assert redact_content("") == ""
