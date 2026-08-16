from careercrew_core.feedback.redaction import redact, redact_value


def test_feedback_redaction_covers_required_sensitive_categories():
    text = (
        "a@b.com 13800138000 11010519491231002X E12345678 sk-abcdef1234567890 "
        "Bearer eyJaaa.bbb.ccc secret=top postgres://u:p@db/x C:\\Users\\sam\\a ~/.ssh/id"
    )
    result = redact(text)
    assert result.count >= 9
    assert result.version == "feedback_snapshot.v1"
    for secret in ("a@b.com", "13800138000", "11010519491231002X", "E12345678", "sk-abcdef1234567890", "eyJaaa", "top", "postgres://", "C:\\Users", "~/.ssh"):
        assert secret not in result.text


def test_feedback_redaction_is_recursive():
    value, count, rules, version = redact_value({"a": ["a@b.com", {"b": "secret=x"}]})
    assert value == {"a": ["[REDACTED]", {"b": "[REDACTED]"}]}
    assert count == 2 and "email" in rules and version == "feedback_snapshot.v1"
