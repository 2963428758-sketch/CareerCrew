"""自建全链路 trace（L3）。TraceContext + JSON Lines，不依赖 LangSmith。"""
from __future__ import annotations

import json
import time
from pathlib import Path


class TraceRecorder:
    """JSON Lines trace 记录器。trace_type: query / ingestion / agent_loop / hitl / memory_op / compaction。"""

    def __init__(self, path: str | Path = "logs/traces.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, trace_type: str, **data) -> None:
        entry = {"ts": time.time(), "trace_type": trace_type, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def agent_loop(self, agent: str, iteration: int, content: str, tool_calls: list, tool_calls_total: int) -> None:
        self.record("agent_loop", agent=agent, iteration=iteration, content=content[:200],
                    tool_calls=tool_calls, tool_calls_total=tool_calls_total)

    def hitl(self, action: str, decision: str) -> None:
        self.record("hitl", action=action, decision=decision)

    def memory_op(self, op: str, entry_id: str, type: str) -> None:
        self.record("memory_op", op=op, entry_id=entry_id, type=type)

    def compaction(self, first_kept_entry_id: str | None, kept: int, compressed: int) -> None:
        self.record("compaction", first_kept_entry_id=first_kept_entry_id, kept=kept, compressed=compressed)

    def read_all(self, limit: int = 200) -> list[dict]:
        if not self.path.exists():
            return []
        lines = [l for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return [json.loads(l) for l in lines[-limit:]]
