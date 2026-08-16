# T5.1 Report — Quality API / RBAC

## Delivered

- Added reviewer-only `GET /api/quality/bad-cases`, detail, `/snapshot`, and
  `/diagnostics` endpoints. The list and detail include every negative-feedback
  record through a dedicated quality view, but never comments, thread IDs,
  message IDs, user IDs, or conversation text.
- Snapshot reads require an active consented snapshot, return the existing
  redacted JSON only, and append a `quality.snapshot.viewed` audit event with
  reviewer ID, snapshot ID, feedback ID, and redaction version only.
- Diagnostics are reachable only through a negative feedback record and expose
  a fixed whitelist of run/retrieval/tool metadata. Query text, tool input,
  tool output summary, run error summary, and all raw messages are excluded.
- Enforced the `quality_reviewer` boundary in the shared authentication
  dependency: reviewers may use `/api/quality/*` plus the existing account
  lifecycle allowlist (`me`, password change, logout), but receive 403 from
  regular conversation/feedback/data endpoints and account management.
- Added matching Postgres/FakeConversationDb quality read models and a focused
  Postgres integration test (guarded by the existing `POSTGRES_TEST_DSN`).

## TDD evidence

`tests/api/test_quality_api.py` was written first. Its initial execution
failed 3 tests because `/api/quality/bad-cases` was not registered (SPA fallback
returned HTML) and no reviewer-only dependency was attached. The implementation
then made the same test file green.

## Verification

```powershell
$env:PYTHONPATH=(Get-Location).Path
& 'F:\Python_develop\miniconda3\envs\careercrew\python.exe' -m pytest \
  tests/api/test_quality_api.py tests/api/test_cross_user_isolation.py \
  tests/api/test_feedback_api.py tests/unit/test_feedback_persistence.py \
  tests/unit/test_quality_reviewer_dependency.py tests/integration/test_conversation_pg.py -q
```

Result: **28 passed, 15 skipped**. The skipped tests are the existing guarded
Postgres integration suite because `POSTGRES_TEST_DSN` is unset. `py_compile`
also passed for the changed backend modules.

`git diff --cached --check` passed.

## Scope / concerns

- No dashboard UI, metrics, review state, bad-case mutation, or Eval work was
  added.
- The full backend suite was started twice, but exceeded this environment's
  30-second command return limit and left processes running; both were stopped.
  This report therefore does not claim a full-suite result.
- Existing unrelated working-tree changes, including their separate Chinese
  error-message edits in `main.py` and `auth/dependencies.py`, were kept
  unstaged. Only the T5.1 hunks are staged.
