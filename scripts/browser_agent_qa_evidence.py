"""Read-only evidence collector for browser-driven Agent QA runs.

The browser remains the execution channel. This helper only reads persisted run,
message, retrieval, and tool-call metadata so QA can verify grounding and tool
decisions without relying on what the UI happens to render.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row


def _dsn() -> str:
    load_dotenv()
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise SystemExit("DATABASE_URL is not configured")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _text(value: object, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit]}...[truncated]"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Collect persisted evidence for browser Agent QA")
    parser.add_argument("--username", required=True)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--since", default="", help="ISO timestamp lower bound")
    parser.add_argument("--answer-limit", type=int, default=6000)
    args = parser.parse_args()

    since = datetime.fromisoformat(args.since) if args.since else None
    where = ["a.username = %s"]
    params: list[object] = [args.username]
    if since is not None:
        where.append("r.created_at >= %s")
        params.append(since)
    params.append(max(1, args.limit))

    sql = f"""
        SELECT r.id::text AS run_id, r.thread_id::text AS thread_id,
               r.turn_id::text AS turn_id, r.message_id::text AS message_id,
               r.module, r.agent_id, r.model, r.prompt_version, r.agent_version,
               r.status, r.latency_ms, r.effective_tools, r.created_at,
               um.content AS input_text, am.content AS answer_text
          FROM agent_runs r
          JOIN auth_accounts a ON a.id = r.user_id
          LEFT JOIN messages am ON am.id = r.message_id
          LEFT JOIN LATERAL (
              SELECT content FROM messages m
               WHERE m.turn_id = r.turn_id AND m.role = 'user'
               ORDER BY m.created_at ASC LIMIT 1
          ) um ON TRUE
         WHERE {' AND '.join(where)}
         ORDER BY r.created_at DESC
         LIMIT %s
    """

    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        out = []
        for row in rows:
            run_id = row["run_id"]
            tools = conn.execute(
                "SELECT tool_name, status, duration_ms, requires_hitl, hitl_status, "
                "error_type, error_summary, output_summary "
                "FROM agent_run_tool_calls WHERE run_id = %s ORDER BY created_at, id",
                (run_id,),
            ).fetchall()
            retrievals = conn.execute(
                "SELECT query_index, scope, document_id, chunk_id, recall_score, rerank_score, "
                "rank_before, rank_after, used_in_final_context "
                "FROM agent_run_retrievals WHERE run_id = %s ORDER BY query_index, rank_after, id",
                (run_id,),
            ).fetchall()
            item = dict(row)
            item["created_at"] = row["created_at"].isoformat()
            item["input_text"] = _text(row.get("input_text"), 3000)
            item["answer_text"] = _text(row.get("answer_text"), args.answer_limit)
            item["tool_calls"] = [
                {
                    **dict(tool),
                    "output_summary": _text(tool.get("output_summary"), 1000),
                    "error_summary": _text(tool.get("error_summary"), 500),
                }
                for tool in tools
            ]
            item["retrievals"] = [dict(retrieval) for retrieval in retrievals]
            out.append(item)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
