import pytest

from careercrew_core.feedback.redaction import redact, redact_value
from careercrew_core.feedback.snapshots import MAX_SNAPSHOT_CHARS, build_snapshot


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


@pytest.mark.parametrize("path", [
    r"C:\Users\sam\secret", "/home/sam/secret", "/Users/sam/secret",
    "/opt/service/secret", "/srv/app/secret", "/mnt/volume/secret", "~/.ssh/id",
])
def test_feedback_redaction_covers_all_local_path_forms_at_boundaries(path):
    result = redact(f"before {path}; after")
    assert path not in result.text
    assert result.text == "before [REDACTED]; after"


def test_feedback_redaction_does_not_match_unrelated_path_prefixes_or_embedded_sensitive_values():
    result = redact("/options/config x13800138000y x11010519491231002Xy")
    assert result.text == "/options/config x13800138000y x11010519491231002Xy"


def test_snapshot_reserves_current_rated_pair_and_redacts_before_truncation():
    user = {"id": "u3", "turn_id": "t3", "role": "user", "content": "q" * 8_000}
    rated = {"id": "a3", "turn_id": "t3", "role": "assistant", "content": "a" * 8_000}
    prior_user = {"id": "u2", "turn_id": "t2", "role": "user", "content": "old"}
    prior_assistant = {"id": "a2", "turn_id": "t2", "role": "assistant", "content": "answer"}
    snapshot, _, _ = build_snapshot([prior_user, prior_assistant, user, rated], rated)
    captured = snapshot["messages"]
    assert [(m["message_id"], len(m["content"])) for m in captured] == [("u3", 6_000), ("a3", 6_000)]
    assert sum(len(m["content"]) for m in captured) == MAX_SNAPSHOT_CHARS


def test_snapshot_redacts_full_source_before_applying_length_limit():
    user = {"id": "u1", "turn_id": "t1", "role": "user", "content": "safe sk-abcdef1234567890"}
    rated = {"id": "a1", "turn_id": "t1", "role": "assistant", "content": "answer"}
    snapshot, count, _ = build_snapshot([user, rated], rated)
    assert snapshot["messages"][0]["content"] == "safe [REDACTED]"
    assert count == 1
