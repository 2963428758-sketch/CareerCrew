"""Bounded, ordered feedback snapshot construction."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from careercrew_core.feedback.redaction import redact

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
    current_user = [m for m in by_turn[rated_turn] if m["role"] == "user"][-1:]
    current_messages = current_user + [rated]
    selected = current_messages[:]
    for turn_id in reversed(prior_turns):
        selected.extend(by_turn[turn_id])

    redacted = []
    count = 0
    for message in selected:
        result = redact(str(message.get("content") or ""))
        redacted.append((message, result.text))
        count += result.count

    captured: list[dict] = []
    current_count = len(current_messages)
    current_pair = redacted[:current_count]
    per_message_budget = MAX_SNAPSHOT_CHARS // current_count
    current_lengths = [min(len(content), per_message_budget) for _message, content in current_pair]
    remaining = MAX_SNAPSHOT_CHARS - sum(current_lengths)
    for index, (_message, content) in enumerate(current_pair):
        additional = min(len(content) - current_lengths[index], remaining)
        current_lengths[index] += additional
        remaining -= additional
    for (message, content), length in zip(current_pair, current_lengths):
        captured.append({
            "role": message["role"], "content": content[:length],
            "turn_id": message["turn_id"], "message_id": message["id"],
        })
    for message, content in redacted[current_count:]:
        if remaining <= 0:
            break
        captured.append({
            "role": message["role"], "content": content[:remaining],
            "turn_id": message["turn_id"], "message_id": message["id"],
        })
        remaining -= min(len(content), remaining)
    return {"messages": captured}, count, "feedback_snapshot.v1"
