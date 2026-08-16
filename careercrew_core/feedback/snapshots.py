"""Bounded, ordered feedback snapshot construction."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from careercrew_core.feedback.redaction import redact_value

MAX_SNAPSHOT_CHARS = 12_000


def build_snapshot(messages: list[dict[str, Any]], rated: dict[str, Any]) -> tuple[dict, int, str]:
    """Return redacted rated-turn-first context, limited to two prior turns and 12k chars."""
    by_turn: dict[str, list[dict]] = defaultdict(list)
    turn_order: list[str] = []
    for message in messages:
        turn_id = message["turn_id"]
        if turn_id not in by_turn:
            turn_order.append(turn_id)
        by_turn[turn_id].append(message)

    rated_turn = rated["turn_id"]
    prior_turns = turn_order[:turn_order.index(rated_turn)][-2:]
    selected = [m for m in by_turn[rated_turn] if m["role"] == "user"]
    selected.append(rated)
    for turn_id in reversed(prior_turns):
        selected.extend(by_turn[turn_id])

    captured: list[dict] = []
    remaining = MAX_SNAPSHOT_CHARS
    for message in selected:
        content = str(message.get("content") or "")
        if remaining <= 0:
            break
        content = content[:remaining]
        remaining -= len(content)
        captured.append({
            "role": message["role"], "content": content,
            "turn_id": message["turn_id"], "message_id": message["id"],
        })
    snapshot, count, _rules, version = redact_value({"messages": captured})
    return snapshot, count, version
