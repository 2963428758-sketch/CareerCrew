# T4.1 — Feedback persistence, privacy snapshots, and user API

## Delivered API contract

- `PUT /api/messages/{message_id}/feedback` accepts only `rating`, optional
  `reason`, optional `comment`, and `share_context` (default `false`). Negative
  feedback requires one of the specified reasons; positive feedback rejects a
  negative reason. The server derives the thread, turn, run, and owner from an
  eligible completed assistant message and returns the same 404 for missing,
  foreign, user, streaming, or run-less messages.
- `DELETE /api/messages/{message_id}/feedback` uses the same ownership gate,
  hard-deletes feedback and snapshot data, and writes only actor/action/resource
  metadata to `feedback_audit_log`.
- `GET /api/threads/{thread_id}/feedback` returns the current owner's persisted
  metadata feedback only. It does not expose snapshots or diagnostics.

## Persistence and privacy implementation

- `ConversationDb` and `FakeConversationDb` now provide aligned feedback,
  snapshot, and audit operations. Postgres creates idempotent
  `message_feedback`, `feedback_snapshots`, and `feedback_audit_log` tables,
  plus the owner/thread feedback index.
- Feedback is upserted by `(user_id, message_id)`. Each replacement removes an
  existing snapshot unless it is negative feedback with explicit
  `share_context=true`; revocation/deletion and conversation clearing remove it
  immediately.
- Snapshot construction keeps the current user question and rated answer first,
  then no more than two preceding turns, capped at 12,000 source characters.
  All captured text recursively passes through the shared
  `feedback_snapshot.v1` redaction service before persistence. It covers email,
  phone, Chinese ID/passport-like values, keys, JWT/Bearer tokens, credentials,
  database URLs, and local/user-home paths. Snapshot expiry is 90 days.

## Verification

```powershell
$env:PYTHONPATH=(Get-Location).Path
& 'F:\Python_develop\miniconda3\envs\careercrew\python.exe' -m pytest tests/unit/test_feedback_redaction.py tests/api/test_feedback_api.py tests/api/test_thread_scope_api.py tests/integration/test_conversation_pg.py -q
```

Result: `12 passed, 12 skipped`. The 12 skipped tests are the existing
Postgres integration module, including the new focused feedback roundtrip; they
are guarded by `POSTGRES_TEST_DSN`, which was not configured in this checkout.
`compileall` and `git diff --check` also passed.

## Deferrals

No frontend persistence wiring, reviewer/dashboard access, Bad Case workflow,
or evaluation work was added; these remain T4.2/Phase 5/Phase 6 scope.
